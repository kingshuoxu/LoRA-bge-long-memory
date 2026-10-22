#include <jni.h>

#include <string>

std::string memory_route_decide(const std::string& index_path, const std::string& text,
                                const float* q, int nq, const float* mq, int nmq);
std::string memory_route_extract(const std::string& key_texts_json);

static std::string jstr(JNIEnv* env, jstring value) {
    const char* utf = env->GetStringUTFChars(value, nullptr);
    std::string out = utf ? utf : "";
    if (utf) env->ReleaseStringUTFChars(value, utf);
    return out;
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
