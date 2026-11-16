#include <jni.h>

#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <unwind.h>

#include <cstring>
#include <string>

std::string memory_route_decide(const std::string& index_path, const std::string& text,
                                const float* q, int nq, const float* mq, int nmq);
std::string memory_route_extract(const std::string& key_texts_json);

static char g_path[512];
static char g_stage[64];
static char g_backend[32];
static int g_armed = 0;

static void append_raw(int fd, const char* text) {
    if (text == nullptr) return;
    size_t n = 0;
    while (text[n] != '\0' && n < 400) n++;
    if (n > 0) write(fd, text, n);
}

static void append_dec(int fd, int value) {
    char tmp[16];
    int n = 0;
    int v = value;
    if (v < 0) v = 0;
    if (v == 0) {
        write(fd, "0", 1);
        return;
    }
    while (v > 0 && n < 15) {
        tmp[n++] = static_cast<char>('0' + (v % 10));
        v /= 10;
    }
    while (n > 0) {
        n--;
        write(fd, &tmp[n], 1);
    }
}

static void append_hex(int fd, uintptr_t value) {
    char tmp[18];
    tmp[0] = '0';
    tmp[1] = 'x';
    for (int i = 0; i < 16; i++) {
        int shift = (15 - i) * 4;
        int nib = static_cast<int>((value >> shift) & 0xf);
        tmp[2 + i] = "0123456789abcdef"[nib];
    }
    write(fd, tmp, 18);
}

struct TraceBuf {
    int fd;
    int frames;
};

static _Unwind_Reason_Code trace_frame(_Unwind_Context* ctx, void* arg) {
    auto* trace = static_cast<TraceBuf*>(arg);
    if (trace->frames >= 16) return _URC_END_OF_STACK;
    uintptr_t pc = _Unwind_GetIP(ctx);
    if (pc == 0) return _URC_END_OF_STACK;
    append_raw(trace->fd, "  ");
    append_hex(trace->fd, pc);
    append_raw(trace->fd, "\n");
    trace->frames++;
    return _URC_NO_REASON;
}

static void on_crash(int sig, siginfo_t* info, void*) {
    int fd = g_path[0] ? open(g_path, O_CREAT | O_WRONLY | O_TRUNC, 0644) : -1;
    if (fd >= 0) {
        append_raw(fd, "signal=");
        append_dec(fd, sig);
        append_raw(fd, "\nstage=");
        append_raw(fd, g_stage);
        append_raw(fd, "\nbackend=");
        append_raw(fd, g_backend);
        append_raw(fd, "\naddr=");
        if (info != nullptr) append_hex(fd, reinterpret_cast<uintptr_t>(info->si_addr));
        append_raw(fd, "\ntrace:\n");
        TraceBuf trace{fd, 0};
        _Unwind_Backtrace(trace_frame, &trace);
        close(fd);
    }
    signal(sig, SIG_DFL);
    raise(sig);
}

static void arm_signals() {
    if (g_armed) return;
    g_armed = 1;
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_sigaction = on_crash;
    sigemptyset(&action.sa_mask);
    action.sa_flags = SA_SIGINFO;
    int sigs[] = {SIGSEGV, SIGABRT, SIGBUS, SIGFPE, SIGILL};
    for (int sig : sigs) sigaction(sig, &action, nullptr);
}

static void copy_field(char* dest, size_t cap, const std::string& value) {
    if (cap == 0) return;
    size_t n = value.size();
    if (n >= cap) n = cap - 1;
    memcpy(dest, value.data(), n);
    dest[n] = '\0';
}

static std::string jstr(JNIEnv* env, jstring value) {
    const char* utf = env->GetStringUTFChars(value, nullptr);
    std::string out = utf ? utf : "";
    if (utf) env->ReleaseStringUTFChars(value, utf);
    return out;
}

extern "C" JNIEXPORT void JNICALL
Java_com_lorabge_memory_NativeRouter_armCrashLog(JNIEnv* env, jobject, jstring path) {
    copy_field(g_path, sizeof(g_path), jstr(env, path));
    arm_signals();
}

extern "C" JNIEXPORT void JNICALL
Java_com_lorabge_memory_NativeRouter_setStage(JNIEnv* env, jobject, jstring stage, jstring backend) {
    copy_field(g_stage, sizeof(g_stage), jstr(env, stage));
    copy_field(g_backend, sizeof(g_backend), jstr(env, backend));
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_lorabge_memory_NativeRouter_decide(JNIEnv* env, jobject, jstring index_path, jstring text,
                                             jfloatArray query, jfloatArray masked) {
    try {
        std::string index = jstr(env, index_path);
        std::string qtext = jstr(env, text);
        jsize nq = query ? env->GetArrayLength(query) : 0;
        jfloat* qv = query && nq > 0 ? env->GetFloatArrayElements(query, nullptr) : nullptr;
        jsize nmq = masked ? env->GetArrayLength(masked) : 0;
        jfloat* mv = masked && nmq > 0 ? env->GetFloatArrayElements(masked, nullptr) : nullptr;
        std::string json = memory_route_decide(index, qtext, qv, static_cast<int>(nq), mv, static_cast<int>(nmq));
        if (qv) env->ReleaseFloatArrayElements(query, qv, JNI_ABORT);
        if (mv) env->ReleaseFloatArrayElements(masked, mv, JNI_ABORT);
        return env->NewStringUTF(json.c_str());
    } catch (const std::exception& ex) {
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"), ex.what());
        return nullptr;
    }
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_lorabge_memory_NativeRouter_extract(JNIEnv* env, jobject, jstring key_texts_json) {
    try {
        std::string json = memory_route_extract(jstr(env, key_texts_json));
        return env->NewStringUTF(json.c_str());
    } catch (const std::exception& ex) {
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"), ex.what());
        return nullptr;
    }
}
