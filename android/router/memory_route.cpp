// 手机侧路由器。移植 scripts/router.py 的实体优先、名字边界和事实闸。
// 不移植改写问句开关和窄带交叉编码器:fact_gate.json 里这两项默认关闭。
// 向量由外部算好(桌面用 PyTorch / 手机用 llama-embedding --pooling mean)。
//
//   memory-route decide --index index.json --queries queries.jsonl --out out.jsonl [--no-fact]
//   memory-route query  --index index.json --embed-cmd 'embed.sh {}' --text '问句'
//   memory-route extract --key-texts key_texts.json

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <unistd.h>

using std::string;
using std::u32string;
using std::vector;
using std::optional;

static void die(const string& msg) {
#ifdef MEMORY_ROUTE_JNI
    throw std::runtime_error(msg);
#else
    std::cerr << msg << "\n";
    std::exit(1);
#endif
}

static bool utf8_decode(const string& in, u32string& out) {
    out.clear();
    out.reserve(in.size());
    for (size_t i = 0; i < in.size();) {
        unsigned char c = static_cast<unsigned char>(in[i]);
        char32_t cp = 0;
        size_t need = 1;
        if (c < 0x80) {
            cp = c;
        } else if ((c & 0xE0) == 0xC0 && i + 1 < in.size()) {
            need = 2;
            cp = ((c & 0x1F) << 6) | (static_cast<unsigned char>(in[i + 1]) & 0x3F);
        } else if ((c & 0xF0) == 0xE0 && i + 2 < in.size()) {
            need = 3;
            cp = ((c & 0x0F) << 12) | ((static_cast<unsigned char>(in[i + 1]) & 0x3F) << 6) |
                 (static_cast<unsigned char>(in[i + 2]) & 0x3F);
        } else if ((c & 0xF8) == 0xF0 && i + 3 < in.size()) {
            need = 4;
            cp = ((c & 0x07) << 18) | ((static_cast<unsigned char>(in[i + 1]) & 0x3F) << 12) |
                 ((static_cast<unsigned char>(in[i + 2]) & 0x3F) << 6) |
                 (static_cast<unsigned char>(in[i + 3]) & 0x3F);
        } else {
            return false;
        }
        out.push_back(cp);
        i += need;
    }
    return true;
}

static string utf8_encode(const u32string& in) {
    string out;
    for (char32_t cp : in) {
        if (cp < 0x80) {
            out.push_back(static_cast<char>(cp));
        } else if (cp < 0x800) {
            out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else if (cp < 0x10000) {
            out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else {
            out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        }
    }
    return out;
}

static u32string U(const char* utf8) {
    u32string out;
    if (!utf8_decode(utf8, out)) die(string("bad utf8 literal: ") + utf8);
    return out;
}

static bool is_py_space(char32_t c) {
    if (c == 0x09 || c == 0x0A || c == 0x0B || c == 0x0C || c == 0x0D || c == 0x20) return true;
    if (c == 0x85 || c == 0xA0 || c == 0x1680) return true;
    if (c >= 0x2000 && c <= 0x200A) return true;
    if (c == 0x2028 || c == 0x2029 || c == 0x202F || c == 0x205F || c == 0x3000) return true;
    return false;
}

static bool is_cjk_ext(char32_t c) { return c >= 0x4E00 && c <= 0x9FFF; }
static bool is_name_han(char32_t c) { return c >= 0x4E00 && c <= 0x9FA5; }

static const u32string NAME_SYLLABLES = U("佐布雷塔尔维纳克洛姆萨丁格鲁佩奥辛达莫菲昆莱索巴特希德温珈缪");

struct PhraseList {
    vector<u32string> items;
    explicit PhraseList(std::initializer_list<const char*> xs) {
        for (const char* s : xs) items.push_back(U(s));
        std::sort(items.begin(), items.end(), [](const u32string& a, const u32string& b) {
            return a.size() > b.size();
        });
    }
};

static const PhraseList LEADS({
    "去哪座城市可以找到", "大家最熟知的", "请告诉我", "能告诉我", "请说出", "谁在管",
    "我想知道", "我想去", "你知道", "查一下", "请问", "谁是", "提到", "诶",
});
static const PhraseList TRAILS({
    "股份有限公司", "有限责任公司", "集团公司", "有限公司", "这家", "集团",
    "公司", "企业", "股份", "控股", "把",
});
static const PhraseList BUSINESS({
    "公司", "集团", "企业", "股份", "董事长", "总经理", "创始人", "老板",
    "CEO", "首席", "总裁", "总部", "成立", "创办", "建厂", "产品", "旗舰",
    "干啥", "咋样", "面试", "掌门", "负责人", "一把手",
});
static const PhraseList SUBJECT_BEFORE({"想问的是", "问的是", "说说", "讲讲"});
static const PhraseList DISMISS_BEFORE({"先别说", "先不说", "别说", "除了"});
static const PhraseList DISMISS_AFTER({"我倒是知道", "我知道"});
static const PhraseList AMBIGUOUS({"相比", "比较", "哪个更", "哪家更", "谁更"});

static u32string PUNCT = U(" \t\u3000:：,，.。?？!！、；;\"'“”‘’（）()【】[]");

static bool contains_cp(const u32string& set, char32_t c) {
    return set.find(c) != u32string::npos;
}

static u32string strip_punct(u32string s) {
    size_t b = 0;
    while (b < s.size() && contains_cp(PUNCT, s[b])) b++;
    size_t e = s.size();
    while (e > b && contains_cp(PUNCT, s[e - 1])) e--;
    return s.substr(b, e - b);
}

static bool starts_with(const u32string& s, const u32string& p) {
    return s.size() >= p.size() && s.compare(0, p.size(), p) == 0;
}
static bool ends_with(const u32string& s, const u32string& p) {
    return s.size() >= p.size() && s.compare(s.size() - p.size(), p.size(), p) == 0;
}
static bool ends_any(const u32string& s, const PhraseList& ps) {
    for (const auto& p : ps.items)
        if (ends_with(s, p)) return true;
    return false;
}
static bool starts_any(const u32string& s, const PhraseList& ps) {
    for (const auto& p : ps.items)
        if (starts_with(s, p)) return true;
    return false;
}
static bool contains_any(const u32string& s, const PhraseList& ps) {
    for (const auto& p : ps.items)
        if (s.find(p) != u32string::npos) return true;
    return false;
}

static u32string strip_affixes(u32string span) {
    span = strip_punct(std::move(span));
    bool changed = true;
    while (changed && !span.empty()) {
        changed = false;
        for (const auto& phrase : LEADS.items) {
            if (starts_with(span, phrase) && span.size() > phrase.size()) {
                span = strip_punct(span.substr(phrase.size()));
                changed = true;
                break;
            }
        }
        if (changed) continue;
        for (const auto& phrase : TRAILS.items) {
            if (ends_with(span, phrase) && span.size() - phrase.size() >= 2) {
                span = strip_punct(span.substr(0, span.size() - phrase.size()));
                changed = true;
                break;
            }
        }
    }
    return span;
}

static optional<u32string> canonicalize_entity(const u32string& span) {
    u32string name = strip_affixes(span);
    if (name.size() < 2 || name.size() > 8) return std::nullopt;
    for (char32_t c : name)
        if (!is_name_han(c)) return std::nullopt;
    return name;
}

static bool is_split_punct(char32_t c) {
    if (is_py_space(c)) return true;
    static const u32string marks = U(",，。！？?!：:、；;");
    return marks.find(c) != u32string::npos;
}

static vector<u32string> registered_names(const vector<string>& raw) {
    vector<u32string> names;
    vector<u32string> seen;
    for (const string& r : raw) {
        u32string u;
        if (!utf8_decode(r, u)) continue;
        auto name = canonicalize_entity(u);
        if (!name) continue;
        if (std::find(seen.begin(), seen.end(), *name) != seen.end()) continue;
        seen.push_back(*name);
        names.push_back(*name);
    }
    return names;
}

static vector<string> extract_entities_from_key_texts(const vector<string>& texts) {
    vector<u32string> found;
    const u32string company = U("公司");
    const u32string group = U("集团");
    for (const string& text : texts) {
        u32string u;
        if (!utf8_decode(text, u)) continue;
        for (size_t i = 0; i < u.size();) {
            bool hit = false;
            size_t nlen = 0;
            if (u.compare(i, company.size(), company) == 0) {
                hit = true;
                nlen = company.size();
            } else if (u.compare(i, group.size(), group) == 0) {
                hit = true;
                nlen = group.size();
            }
            if (!hit) {
                i++;
                continue;
            }
            size_t cut = 0;
            for (size_t k = i; k-- > 0;) {
                if (is_split_punct(u[k])) {
                    cut = k + 1;
                    break;
                }
                if (k == 0) break;
            }
            auto name = canonicalize_entity(u.substr(cut, i - cut));
            if (name && std::find(found.begin(), found.end(), *name) == found.end()) found.push_back(*name);
            i += nlen;
        }
    }
    std::stable_sort(found.begin(), found.end(), [](const u32string& a, const u32string& b) {
        return a.size() > b.size();
    });
    vector<string> out;
    for (const auto& n : found) out.push_back(utf8_encode(n));
    return out;
}

static u32string compact_query(const u32string& q) {
    u32string out;
    for (char32_t c : q)
        if (!is_py_space(c)) out.push_back(c);
    return out;
}

static const u32string SHORT_LEFT = U("到问说下是去于我管道和出的");
static const u32string SHORT_RIGHT = U("公的集这是企股吧咋和最现我相了把总主产");

static bool short_name_neighbors_ok(const u32string& compact, int start, int end) {
    if (end - start > 2) return true;
    if (start > 0 && is_cjk_ext(compact[start - 1]) && !contains_cp(SHORT_LEFT, compact[start - 1])) return false;
    if (end < static_cast<int>(compact.size()) && is_cjk_ext(compact[end]) && !contains_cp(SHORT_RIGHT, compact[end]))
        return false;
    return true;
}

static vector<u32string> mentioned_entities(const u32string& query, const vector<string>& raw) {
    auto names = registered_names(raw);
    if (names.empty()) return {};
    u32string compact = compact_query(query);
    vector<char32_t> alphabet;
    auto add_alpha = [&](char32_t c) {
        if (std::find(alphabet.begin(), alphabet.end(), c) == alphabet.end()) alphabet.push_back(c);
    };
    for (char32_t c : NAME_SYLLABLES) add_alpha(c);
    for (const auto& name : names)
        for (char32_t c : name) add_alpha(c);
    auto in_alpha = [&](char32_t c) {
        return std::find(alphabet.begin(), alphabet.end(), c) != alphabet.end();
    };
    vector<u32string> ordered = names;
    std::stable_sort(ordered.begin(), ordered.end(), [](const u32string& a, const u32string& b) {
        return a.size() > b.size();
    });
    vector<char> occupied(compact.size(), 0);
    vector<u32string> hits;
    for (const auto& entity : ordered) {
        size_t search = 0;
        while (true) {
            size_t index = compact.find(entity, search);
            if (index == u32string::npos) break;
            int end = static_cast<int>(index + entity.size());
            search = index + 1;
            bool overlap = false;
            for (int p = static_cast<int>(index); p < end; p++)
                if (occupied[p]) overlap = true;
            if (overlap) continue;
            if (index > 0 && in_alpha(compact[index - 1])) continue;
            if (end < static_cast<int>(compact.size()) && in_alpha(compact[end])) continue;
            if (!short_name_neighbors_ok(compact, static_cast<int>(index), end)) continue;
            hits.push_back(entity);
            for (int p = static_cast<int>(index); p < end; p++) occupied[p] = 1;
        }
    }
    return hits;
}

struct Span {
    u32string text;
    int start;
    int end;
};

static vector<Span> find_name_spans(const u32string& compact) {
    vector<Span> spans;
    int i = 0;
    int n = static_cast<int>(compact.size());
    while (i < n) {
        if (contains_cp(NAME_SYLLABLES, compact[i])) {
            int j = i + 1;
            while (j < n && contains_cp(NAME_SYLLABLES, compact[j])) j++;
            if (j - i >= 2) spans.push_back({compact.substr(i, j - i), i, j});
            i = j;
        } else {
            i++;
        }
    }
    return spans;
}

static bool cue_near(const u32string& compact, int start, int end) {
    for (const auto& cue : BUSINESS.items) {
        size_t from = 0;
        while (true) {
            size_t index = compact.find(cue, from);
            if (index == u32string::npos) break;
            int cue_end = static_cast<int>(index + cue.size());
            from = index + 1;
            if (static_cast<int>(index) < end && cue_end > start) continue;
            int gap = cue_end <= start ? start - cue_end : static_cast<int>(index) - end;
            if (gap <= 12) return true;
        }
    }
    return false;
}

static optional<u32string> pick_subject(const u32string& compact, const vector<Span>& spans) {
    vector<u32string> subjects;
    vector<int> dismissed;
    for (const auto& span : spans) {
        int left_from = std::max(0, span.start - 12);
        u32string left = compact.substr(left_from, span.start - left_from);
        int right_n = std::min(12, static_cast<int>(compact.size()) - span.end);
        u32string right = right_n > 0 ? compact.substr(span.end, right_n) : u32string();
        if (ends_any(left, DISMISS_BEFORE) || starts_any(right, DISMISS_AFTER)) dismissed.push_back(span.start);
        if (ends_any(left, SUBJECT_BEFORE)) subjects.push_back(span.text);
    }
    if (subjects.size() == 1) return subjects[0];
    if (contains_any(compact, AMBIGUOUS)) return std::nullopt;
    vector<u32string> survivors;
    for (const auto& span : spans) {
        if (std::find(dismissed.begin(), dismissed.end(), span.start) == dismissed.end()) survivors.push_back(span.text);
    }
    if (survivors.size() == 1 && !dismissed.empty()) return survivors[0];
    return std::nullopt;
}

struct Expert {
    string name;
    vector<string> entities;
    vector<float> keys;
    int n_keys = 0;
};

struct FactRow {
    string entity;
    u32string entity_u;
};

struct FactGate {
    bool enabled = false;
    double tau = 0.622;
    u32string mask = U("某");
    int dim = 0;
    vector<FactRow> rows;
    vector<float> vec;
    vector<u32string> names_by_len;
    struct SpanE {
        string entity;
        u32string entity_u;
        int start;
        int end;
    };
    vector<SpanE> spans;
    vector<vector<char>> keep;
};

struct Index {
    double tau = 0.6;
    int dim = 0;
    vector<Expert> experts;
    FactGate facts;
    string dir;
};

struct SimList {
    vector<std::pair<string, double>> items;
    bool has(const string& k) const {
        for (const auto& kv : items)
            if (kv.first == k) return true;
        return false;
    }
    double get(const string& k, double fallback) const {
        for (const auto& kv : items)
            if (kv.first == k) return kv.second;
        return fallback;
    }
};

struct Decision {
    optional<string> expert;
    optional<string> candidate;
    bool fired = false;
    string reason;
    double sim = 0;
    double own = -1;
    double other = -1;
    bool fact_scored = false;
};

static double dot(const float* a, const float* b, int n) {
    double s = 0;
    for (int i = 0; i < n; i++) s += static_cast<double>(a[i]) * static_cast<double>(b[i]);
    return s;
}

static u32string mask_query_u(u32string query, const vector<u32string>& names, const u32string& mask) {
    for (const auto& name : names) {
        if (name.empty()) continue;
        size_t pos = 0;
        while ((pos = query.find(name, pos)) != u32string::npos) {
            query.replace(pos, name.size(), mask);
            pos += mask.size();
        }
    }
    return query;
}

static std::pair<double, double> fact_scores(const FactGate& gate, const float* q, size_t span_i) {
    const auto& span = gate.spans[span_i];
    if (span.end <= span.start || q == nullptr) return {-1.0, -1.0};
    double own = -1e9;
    for (int i = span.start; i < span.end; i++) {
        own = std::max(own, dot(q, gate.vec.data() + static_cast<size_t>(i) * gate.dim, gate.dim));
    }
    const auto& keep = gate.keep[span_i];
    bool any = false;
    double other = -1e9;
    for (int i = 0; i < static_cast<int>(gate.rows.size()); i++) {
        if (!keep[i]) continue;
        any = true;
        other = std::max(other, dot(q, gate.vec.data() + static_cast<size_t>(i) * gate.dim, gate.dim));
    }
    if (!any) return {own, -1.0};
    return {own, other};
}

static bool fact_allows(const FactGate& gate, const float* mq, const u32string& name, double& own, double& other) {
    if (!gate.enabled) return true;
    int span_i = -1;
    for (size_t i = 0; i < gate.spans.size(); i++)
        if (gate.spans[i].entity_u == name) {
            span_i = static_cast<int>(i);
            break;
        }
    if (span_i < 0 || mq == nullptr) {
        own = -1;
        other = -1;
        return false;
    }
    auto sc = fact_scores(gate, mq, static_cast<size_t>(span_i));
    own = sc.first;
    other = sc.second;
    return own >= gate.tau && own + 1e-6 >= other;
}

static Decision route_decision(
    const u32string& query,
    const vector<Expert>& experts,
    const SimList& sims,
    double tau,
    const FactGate* gate,
    const float* mq) {
    std::map<u32string, optional<string>> owners;
    auto entity_of = [&](const string& expert) -> const vector<string>* {
        for (const auto& e : experts)
            if (e.name == expert) return &e.entities;
        return nullptr;
    };
    for (const auto& expert : experts) {
        for (const auto& name : registered_names(expert.entities)) {
            auto it = owners.find(name);
            if (it != owners.end()) {
                if (!it->second || *it->second != expert.name) it->second = std::nullopt;
            } else {
                owners.emplace(name, expert.name);
            }
        }
    }
    auto owner_of = [&](const u32string& name) -> optional<string> {
        auto it = owners.find(name);
        if (it == owners.end()) return std::nullopt;
        return it->second;
    };

    u32string compact = compact_query(query);
    auto spans = find_name_spans(compact);
    optional<string> best;
    double best_sim = 0;
    for (const auto& kv : sims.items) {
        if (!best || kv.second > best_sim) {
            best = kv.first;
            best_sim = kv.second;
        }
    }

    auto blocked = [&](const string& reason) {
        Decision d;
        d.candidate = best;
        d.fired = false;
        d.reason = reason;
        d.sim = best_sim;
        return d;
    };

    auto apply_fact = [&](Decision d, const u32string& name) {
        if (!gate || !gate->enabled) return d;
        double own = -1, other = -1;
        bool ok = fact_allows(*gate, mq, name, own, other);
        d.fact_scored = true;
        d.own = own;
        d.other = other;
        if (!ok) {
            d.expert = std::nullopt;
            d.fired = false;
            d.reason = "abstain_fact";
            d.sim = best_sim;
            d.candidate = best;
        }
        return d;
    };

    auto bge_fallback = [&]() {
        if (!best) return blocked("no_expert");
        const vector<string>* raw = entity_of(*best);
        vector<string> empty;
        const vector<string>& use = raw ? *raw : empty;
        auto names = mentioned_entities(query, use);
        bool guard = false;
        if (raw && !raw->empty()) guard = !names.empty();
        else guard = true;
        if (best_sim < tau || !guard) return blocked("bge_block");
        Decision d;
        d.expert = best;
        d.candidate = best;
        d.fired = true;
        d.reason = "bge";
        d.sim = best_sim;
        if (gate && gate->enabled && !names.empty()) {
            bool any = false;
            double own = -1, other = -1;
            for (const auto& name : names) {
                double o = -1, t = -1;
                if (fact_allows(*gate, mq, name, o, t)) {
                    any = true;
                    own = o;
                    other = t;
                    break;
                }
                own = o;
                other = t;
            }
            d.fact_scored = true;
            d.own = own;
            d.other = other;
            if (!any) {
                d.expert = std::nullopt;
                d.fired = false;
                d.reason = "abstain_fact";
            }
        }
        return d;
    };

    if (spans.size() >= 2) {
        auto subject = pick_subject(compact, spans);
        if (!subject) return blocked("abstain");
        auto expert = owner_of(*subject);
        const Span* span = nullptr;
        for (const auto& item : spans)
            if (item.text == *subject) {
                span = &item;
                break;
            }
        bool neighbor_ok = span && short_name_neighbors_ok(compact, span->start, span->end);
        if (expert && span && neighbor_ok && cue_near(compact, span->start, span->end)) {
            Decision d;
            d.expert = expert;
            d.candidate = expert;
            d.fired = true;
            d.reason = "subject";
            d.sim = sims.get(*expert, 0.0);
            return apply_fact(d, *subject);
        }
        string reason;
        if (expert && span && neighbor_ok) reason = "abstain_no_cue";
        else if (span && !neighbor_ok) reason = "abstain_short_name";
        else reason = "abstain_unregistered_subject";
        return blocked(reason);
    }

    if (spans.size() == 1) {
        const auto& span = spans[0];
        auto expert = owner_of(span.text);
        if (expert && short_name_neighbors_ok(compact, span.start, span.end) && cue_near(compact, span.start, span.end)) {
            Decision d;
            d.expert = expert;
            d.candidate = expert;
            d.fired = true;
            d.reason = "entity";
            d.sim = sims.get(*expert, 0.0);
            return apply_fact(d, span.text);
        }
    }
    return bge_fallback();
}

// ---------- minimal JSON ----------

struct Json {
    enum Type { NUL, BOOL, NUM, STR, ARR, OBJ } type = NUL;
    bool b = false;
    double n = 0;
    string s;
    vector<Json> a;
    vector<std::pair<string, Json>> o;
    const Json* get(const string& k) const {
        for (const auto& kv : o)
            if (kv.first == k) return &kv.second;
        return nullptr;
    }
    bool has(const string& k) const { return get(k) != nullptr; }
};

struct Parser {
    const string& in;
    size_t i = 0;
    explicit Parser(const string& s) : in(s) {}
    void skip() {
        while (i < in.size() && (in[i] == ' ' || in[i] == '\t' || in[i] == '\n' || in[i] == '\r')) i++;
    }
    char peek() {
        skip();
        return i < in.size() ? in[i] : 0;
    }
    char getc() {
        skip();
        if (i >= in.size()) die("json truncated");
        return in[i++];
    }
    Json parse() {
        char c = peek();
        if (c == '{') return parse_obj();
        if (c == '[') return parse_arr();
        if (c == '"') {
            Json j;
            j.type = Json::STR;
            j.s = parse_str();
            return j;
        }
        if (c == 't' || c == 'f') return parse_bool();
        if (c == 'n') return parse_null();
        if (c == '-' || (c >= '0' && c <= '9')) return parse_num();
        die(string("json bad char at ") + std::to_string(i));
        return {};
    }
    Json parse_obj() {
        getc();
        Json j;
        j.type = Json::OBJ;
        if (peek() == '}') {
            getc();
            return j;
        }
        while (true) {
            if (peek() != '"') die("json key");
            string key = parse_str();
            if (getc() != ':') die("json colon");
            j.o.emplace_back(key, parse());
            char c = getc();
            if (c == '}') break;
            if (c != ',') die("json comma");
        }
        return j;
    }
    Json parse_arr() {
        getc();
        Json j;
        j.type = Json::ARR;
        if (peek() == ']') {
            getc();
            return j;
        }
        while (true) {
            j.a.push_back(parse());
            char c = getc();
            if (c == ']') break;
            if (c != ',') die("json comma arr");
        }
        return j;
    }
    Json parse_bool() {
        Json j;
        j.type = Json::BOOL;
        if (in.compare(i, 4, "true") == 0) {
            i += 4;
            j.b = true;
            return j;
        }
        if (in.compare(i, 5, "false") == 0) {
            i += 5;
            j.b = false;
            return j;
        }
        die("json bool");
        return j;
    }
    Json parse_null() {
        if (in.compare(i, 4, "null") != 0) die("json null");
        i += 4;
        Json j;
        j.type = Json::NUL;
        return j;
    }
    Json parse_num() {
        skip();
        size_t start = i;
        if (in[i] == '-') i++;
        while (i < in.size() && ((in[i] >= '0' && in[i] <= '9') || in[i] == '.' || in[i] == 'e' || in[i] == 'E' ||
                                 in[i] == '+' || in[i] == '-')) {
            if ((in[i] == '+' || in[i] == '-') && i != start && in[i - 1] != 'e' && in[i - 1] != 'E') break;
            i++;
        }
        Json j;
        j.type = Json::NUM;
        j.n = std::strtod(in.c_str() + start, nullptr);
        return j;
    }
    string parse_str() {
        if (getc() != '"') die("json str");
        string out;
        while (i < in.size()) {
            char c = in[i++];
            if (c == '"') return out;
            if (c == '\\') {
                if (i >= in.size()) die("json esc");
                char e = in[i++];
                if (e == '"' || e == '\\' || e == '/') out.push_back(e);
                else if (e == 'b') out.push_back('\b');
                else if (e == 'f') out.push_back('\f');
                else if (e == 'n') out.push_back('\n');
                else if (e == 'r') out.push_back('\r');
                else if (e == 't') out.push_back('\t');
                else if (e == 'u') {
                    if (i + 4 > in.size()) die("json u");
                    int cp = 0;
                    for (int k = 0; k < 4; k++) {
                        char h = in[i++];
                        cp <<= 4;
                        if (h >= '0' && h <= '9') cp += h - '0';
                        else if (h >= 'a' && h <= 'f') cp += h - 'a' + 10;
                        else if (h >= 'A' && h <= 'F') cp += h - 'A' + 10;
                        else die("json hex");
                    }
                    u32string u;
                    u.push_back(static_cast<char32_t>(cp));
                    out += utf8_encode(u);
                } else die("json esc bad");
            } else {
                out.push_back(c);
            }
        }
        die("json str end");
        return out;
    }
};

static Json parse_json(const string& s) {
    Parser p(s);
    return p.parse();
}

static string read_file(const string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) die("cannot read " + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

static string dirname_of(const string& path) {
    auto pos = path.find_last_of('/');
    if (pos == string::npos) return ".";
    if (pos == 0) return "/";
    return path.substr(0, pos);
}

static string join_path(const string& dir, const string& rel) {
    if (rel.empty() || rel[0] == '/') return rel;
    return dir + "/" + rel;
}

static vector<float> load_f32(const string& path, int n, int dim) {
    std::ifstream in(path, std::ios::binary);
    if (!in) die("cannot read " + path);
    vector<float> v(static_cast<size_t>(n) * dim);
    in.read(reinterpret_cast<char*>(v.data()), v.size() * sizeof(float));
    if (in.gcount() != static_cast<std::streamsize>(v.size() * sizeof(float))) die("short float file " + path);
    return v;
}

static vector<string> json_str_arr(const Json& j) {
    if (j.type != Json::ARR) die("expected array");
    vector<string> out;
    for (const auto& x : j.a) {
        if (x.type != Json::STR) die("expected string");
        out.push_back(x.s);
    }
    return out;
}

static Index load_index(const string& path, bool no_fact) {
    Index idx;
    idx.dir = dirname_of(path);
    Json root = parse_json(read_file(path));
    if (root.has("tau") && root.get("tau")->type == Json::NUM) idx.tau = root.get("tau")->n;
    if (root.has("dim") && root.get("dim")->type == Json::NUM) idx.dim = static_cast<int>(root.get("dim")->n);
    const Json* experts = root.get("experts");
    if (!experts || experts->type != Json::ARR) die("index.experts");
    for (const auto& e : experts->a) {
        Expert ex;
        ex.name = e.get("name")->s;
        if (e.has("entities")) ex.entities = json_str_arr(*e.get("entities"));
        if (e.has("n_keys")) ex.n_keys = static_cast<int>(e.get("n_keys")->n);
        if (e.has("keys") && ex.n_keys > 0) {
            if (idx.dim <= 0) die("index.dim required");
            ex.keys = load_f32(join_path(idx.dir, e.get("keys")->s), ex.n_keys, idx.dim);
        }
        idx.experts.push_back(std::move(ex));
    }
    if (!no_fact && root.has("facts") && root.get("facts")->type == Json::OBJ) {
        const Json& f = *root.get("facts");
        FactGate gate;
        if (f.has("tau")) gate.tau = f.get("tau")->n;
        if (f.has("mask") && f.get("mask")->type == Json::STR) {
            if (!utf8_decode(f.get("mask")->s, gate.mask)) die("mask utf8");
        }
        const Json* rows = f.get("rows");
        if (rows && rows->type == Json::ARR && !rows->a.empty()) {
            gate.enabled = true;
            gate.dim = idx.dim;
            if (gate.dim <= 0) die("dim required for facts");
            for (const auto& row : rows->a) {
                FactRow fr;
                fr.entity = row.get("entity")->s;
                if (!utf8_decode(fr.entity, fr.entity_u)) die("entity utf8");
                gate.rows.push_back(std::move(fr));
            }
            gate.vec = load_f32(join_path(idx.dir, f.get("vectors")->s), static_cast<int>(gate.rows.size()), gate.dim);
            vector<u32string> order;
            for (const auto& row : gate.rows) {
                if (std::find(order.begin(), order.end(), row.entity_u) == order.end()) order.push_back(row.entity_u);
            }
            gate.names_by_len = order;
            std::stable_sort(gate.names_by_len.begin(), gate.names_by_len.end(), [](const u32string& a, const u32string& b) {
                return a.size() > b.size();
            });
            for (size_t i = 0; i < gate.rows.size();) {
                size_t j = i + 1;
                while (j < gate.rows.size() && gate.rows[j].entity == gate.rows[i].entity) j++;
                FactGate::SpanE span;
                span.entity = gate.rows[i].entity;
                span.entity_u = gate.rows[i].entity_u;
                span.start = static_cast<int>(i);
                span.end = static_cast<int>(j);
                gate.spans.push_back(span);
                i = j;
            }
            gate.keep.resize(gate.spans.size());
            for (size_t s = 0; s < gate.spans.size(); s++) {
                const auto& span = gate.spans[s];
                vector<char> dup(gate.rows.size(), 0);
                for (int i = 0; i < static_cast<int>(gate.rows.size()); i++) {
                    double mx = -2;
                    for (int j = span.start; j < span.end; j++) {
                        mx = std::max(mx, dot(gate.vec.data() + static_cast<size_t>(i) * gate.dim,
                                              gate.vec.data() + static_cast<size_t>(j) * gate.dim, gate.dim));
                    }
                    dup[i] = mx >= 0.999 ? 1 : 0;
                }
                for (int j = span.start; j < span.end; j++) dup[j] = 1;
                gate.keep[s].resize(gate.rows.size());
                for (size_t i = 0; i < dup.size(); i++) gate.keep[s][i] = dup[i] ? 0 : 1;
            }
        }
        idx.facts = std::move(gate);
    }
    return idx;
}

static string json_escape(const string& s) {
    string o;
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') {
            o.push_back('\\');
            o.push_back(static_cast<char>(c));
        } else if (c == '\n') o += "\\n";
        else if (c < 0x20) {
            char buf[8];
            std::snprintf(buf, sizeof(buf), "\\u%04x", c);
            o += buf;
        } else o.push_back(static_cast<char>(c));
    }
    return o;
}

static void write_decision(std::ostream& out, const string& id, const Decision& d) {
    out << "{\"id\":\"" << json_escape(id) << "\"";
    out << ",\"expert\":";
    if (d.expert) out << "\"" << json_escape(*d.expert) << "\"";
    else out << "null";
    out << ",\"candidate\":";
    if (d.candidate) out << "\"" << json_escape(*d.candidate) << "\"";
    else out << "null";
    out << ",\"fired\":" << (d.fired ? "true" : "false");
    out << ",\"reason\":\"" << json_escape(d.reason) << "\"";
    out << ",\"sim\":" << d.sim;
    if (d.fact_scored) out << ",\"own\":" << d.own << ",\"other\":" << d.other;
    out << "}\n";
}

static vector<Expert> experts_override(const Json& ent, const vector<Expert>& base) {
    vector<Expert> out;
    for (const auto& kv : ent.o) {
        Expert e;
        e.name = kv.first;
        e.entities = json_str_arr(kv.second);
        for (const auto& b : base)
            if (b.name == e.name) {
                e.keys = b.keys;
                e.n_keys = b.n_keys;
            }
        out.push_back(std::move(e));
    }
    return out;
}

static SimList sims_from_json(const Json& obj) {
    SimList s;
    for (const auto& kv : obj.o) {
        if (kv.second.type != Json::NUM) die("sim not number");
        s.items.emplace_back(kv.first, kv.second.n);
    }
    return s;
}

static SimList sims_from_vec(const vector<Expert>& experts, const float* q, int dim) {
    SimList s;
    for (const auto& e : experts) {
        double m = 0;
        if (e.n_keys > 0 && !e.keys.empty()) {
            m = -2;
            for (int i = 0; i < e.n_keys; i++) {
                m = std::max(m, dot(q, e.keys.data() + static_cast<size_t>(i) * dim, dim));
            }
        }
        s.items.emplace_back(e.name, m);
    }
    return s;
}

static const float* row_ptr(const vector<float>& buf, int row, int dim) {
    if (row < 0) return nullptr;
    size_t off = static_cast<size_t>(row) * dim;
    if (off + dim > buf.size()) die("vector row out of range");
    return buf.data() + off;
}

static int cmd_decide(int argc, char** argv) {
    string index_path, queries_path, out_path, qvec_path, mqvec_path;
    bool no_fact = false;
    for (int i = 2; i < argc; i++) {
        string a = argv[i];
        auto need = [&](const string& name) {
            if (i + 1 >= argc) die("missing value for " + name);
            return string(argv[++i]);
        };
        if (a == "--index") index_path = need(a);
        else if (a == "--queries") queries_path = need(a);
        else if (a == "--out") out_path = need(a);
        else if (a == "--q-vectors") qvec_path = need(a);
        else if (a == "--mq-vectors") mqvec_path = need(a);
        else if (a == "--no-fact") no_fact = true;
        else die("unknown arg " + a);
    }
    if (index_path.empty() || queries_path.empty() || out_path.empty()) die("decide needs --index --queries --out");
    Index idx = load_index(index_path, no_fact);
    vector<float> qvecs, mqvecs;
    auto load_all = [](const string& path) {
        std::ifstream in(path, std::ios::binary);
        if (!in) die("cannot read " + path);
        in.seekg(0, std::ios::end);
        auto n = in.tellg();
        in.seekg(0);
        vector<float> v(static_cast<size_t>(n) / sizeof(float));
        in.read(reinterpret_cast<char*>(v.data()), v.size() * sizeof(float));
        return v;
    };
    if (!qvec_path.empty()) qvecs = load_all(qvec_path);
    if (!mqvec_path.empty()) mqvecs = load_all(mqvec_path);
    std::ifstream in(queries_path);
    if (!in) die("cannot read queries");
    std::ofstream out(out_path);
    if (!out) die("cannot write out");
    string line;
    int n = 0;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        Json q = parse_json(line);
        string id = q.has("id") && q.get("id")->type == Json::STR ? q.get("id")->s : std::to_string(n);
        u32string query;
        if (!q.has("q") || !utf8_decode(q.get("q")->s, query)) die("query utf8 " + id);
        vector<Expert> experts = idx.experts;
        if (q.has("entities") && q.get("entities")->type == Json::OBJ) experts = experts_override(*q.get("entities"), idx.experts);
        const float* qv = nullptr;
        const float* mq = nullptr;
        if (q.has("q_row")) qv = row_ptr(qvecs, static_cast<int>(q.get("q_row")->n), idx.dim);
        if (q.has("mq_row")) mq = row_ptr(mqvecs, static_cast<int>(q.get("mq_row")->n), idx.dim);
        SimList sims;
        if (q.has("sims")) sims = sims_from_json(*q.get("sims"));
        else if (qv) sims = sims_from_vec(experts, qv, idx.dim);
        const FactGate* gate = idx.facts.enabled ? &idx.facts : nullptr;
        if (gate && !mq && !q.has("sims")) die("fact gate needs mq_row for " + id);
        // 逻辑对照只传 sims、不传掩码向量时,事实闸不参与(与 fact_memory=None 一致)。
        if (gate && !mq) gate = nullptr;
        Decision d = route_decision(query, experts, sims, idx.tau, gate, mq);
        write_decision(out, id, d);
        n++;
    }
    std::cerr << "decisions " << n << "\n";
    return 0;
}

static vector<float> run_embed(const string& cmd_tmpl, const string& text, int dim) {
    char path[] = "/tmp/route-text-XXXXXX";
    int fd = mkstemp(path);
    if (fd < 0) die("mkstemp");
    if (write(fd, text.data(), text.size()) != static_cast<ssize_t>(text.size())) die("write text");
    close(fd);
    string cmd = cmd_tmpl;
    auto pos = cmd.find("{}");
    if (pos == string::npos) die("embed-cmd must contain {}");
    cmd.replace(pos, 2, path);
    string out_path = string(path) + ".vec";
    string full = cmd + " > " + out_path;
    int rc = std::system(full.c_str());
    ::unlink(path);
    if (rc != 0) die("embed command failed");
    string body = read_file(out_path);
    ::unlink(out_path.c_str());
    for (char& c : body)
        if (c == ',' || c == '[' || c == ']') c = ' ';
    std::stringstream ss(body);
    vector<float> nums;
    double x;
    while (ss >> x) nums.push_back(static_cast<float>(x));
    if (static_cast<int>(nums.size()) < dim) die("embed returned too few floats");
    if (static_cast<int>(nums.size()) > dim) nums.erase(nums.begin(), nums.end() - dim);
    return nums;
}

static int cmd_query(int argc, char** argv) {
    string index_path, embed_cmd, text;
    bool no_fact = false;
    for (int i = 2; i < argc; i++) {
        string a = argv[i];
        auto need = [&]() {
            if (i + 1 >= argc) die("missing value");
            return string(argv[++i]);
        };
        if (a == "--index") index_path = need();
        else if (a == "--embed-cmd") embed_cmd = need();
        else if (a == "--text") text = need();
        else if (a == "--text-file") text = read_file(need());
        else if (a == "--no-fact") no_fact = true;
        else die("unknown arg " + a);
    }
    if (index_path.empty() || embed_cmd.empty() || text.empty()) die("query needs --index --embed-cmd --text");
    Index idx = load_index(index_path, no_fact);
    if (idx.dim <= 0) die("index.dim required");
    auto qv = run_embed(embed_cmd, text, idx.dim);
    u32string query;
    if (!utf8_decode(text, query)) die("text utf8");
    vector<float> mv;
    const float* mq = nullptr;
    if (idx.facts.enabled) {
        u32string masked = mask_query_u(query, idx.facts.names_by_len, idx.facts.mask);
        mv = run_embed(embed_cmd, utf8_encode(masked), idx.dim);
        mq = mv.data();
    }
    SimList sims = sims_from_vec(idx.experts, qv.data(), idx.dim);
    const FactGate* gate = idx.facts.enabled ? &idx.facts : nullptr;
    Decision d = route_decision(query, idx.experts, sims, idx.tau, gate, mq);
    write_decision(std::cout, "query", d);
    return 0;
}

static int cmd_extract(int argc, char** argv) {
    string path;
    for (int i = 2; i < argc; i++) {
        if (string(argv[i]) == "--key-texts" && i + 1 < argc) path = argv[++i];
        else die("unknown arg");
    }
    if (path.empty()) die("extract needs --key-texts");
    Json root = parse_json(read_file(path));
    auto texts = json_str_arr(root);
    auto names = extract_entities_from_key_texts(texts);
    std::cout << "[";
    for (size_t i = 0; i < names.size(); i++) {
        if (i) std::cout << ",";
        std::cout << "\"" << json_escape(names[i]) << "\"";
    }
    std::cout << "]\n";
    return 0;
}

string memory_route_decide(const string& index_path, const string& text, const float* q, int nq, const float* mq, int nmq) {
    Index idx = load_index(index_path, false);
    if (idx.dim <= 0) die("index.dim required");
    if (q == nullptr || nq != idx.dim) die("query vector dim");
    const float* mqptr = nullptr;
    if (mq != nullptr) {
        if (nmq != idx.dim) die("masked vector dim");
        mqptr = mq;
    }
    u32string query;
    if (!utf8_decode(text, query)) die("text utf8");
    SimList sims = sims_from_vec(idx.experts, q, idx.dim);
    const FactGate* gate = (idx.facts.enabled && mqptr) ? &idx.facts : nullptr;
    Decision d = route_decision(query, idx.experts, sims, idx.tau, gate, mqptr);
    std::ostringstream out;
    write_decision(out, "query", d);
    return out.str();
}

string memory_route_extract(const string& key_texts_json) {
    Json root = parse_json(key_texts_json);
    auto texts = json_str_arr(root);
    auto names = extract_entities_from_key_texts(texts);
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < names.size(); i++) {
        if (i) out << ",";
        out << "\"" << json_escape(names[i]) << "\"";
    }
    out << "]";
    return out.str();
}

int main(int argc, char** argv) {
    if (argc < 2) die("usage: memory-route decide|query|extract ...");
    string cmd = argv[1];
    if (cmd == "decide") return cmd_decide(argc, argv);
    if (cmd == "query") return cmd_query(argc, argv);
    if (cmd == "extract") return cmd_extract(argc, argv);
    die("unknown command " + cmd);
    return 1;
}
