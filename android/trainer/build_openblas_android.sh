#!/bin/sh
# 给手机训练程序编一份 arm64 OpenBLAS。纯 C++ GEMM 在这台 Xeon 上一个微批要 11 秒,
# 450 行的研究批次会拖到几小时。ARMv8 NEON 这份静态库链进 libtrain-mft.so。
# 用 ARMV8 而不是 NEOVERSE/SVE:小米 15 的 Oryon 能跑 NEON,SVE 目标没有在这台机器上核对过。
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")"/../.. && pwd)
PREFIX=${OPENBLAS_PREFIX:-$ROOT/android/trainer/openblas-android}
SRC=${OPENBLAS_SRC:-/tmp/OpenBLAS}
TAG=${OPENBLAS_TAG:-v0.3.28}
NDK=${ANDROID_NDK_ROOT:-${ANDROID_NDK_HOME:-}}
if [ -z "$NDK" ] && [ -n "${ANDROID_HOME:-}" ] && [ -d "$ANDROID_HOME/ndk" ]; then
  NDK=$(find "$ANDROID_HOME/ndk" -maxdepth 1 -mindepth 1 -type d | sort | tail -n 1)
fi
if [ -z "$NDK" ] || [ ! -d "$NDK/toolchains/llvm/prebuilt" ]; then
  echo "找不到 Android NDK。设置 ANDROID_NDK_ROOT。" >&2
  exit 1
fi
HOST=$(find "$NDK/toolchains/llvm/prebuilt" -maxdepth 1 -mindepth 1 -type d | head -1)
API=${ANDROID_API:-29}
CC="$HOST/bin/aarch64-linux-android${API}-clang"
AR="$HOST/bin/llvm-ar"
RANLIB="$HOST/bin/llvm-ranlib"
if [ ! -x "$CC" ]; then
  echo "找不到 $CC" >&2
  exit 1
fi
write_cblas_header() {
  mkdir -p "$PREFIX/include"
  cat > "$PREFIX/include/cblas.h" << 'EOF'
#ifndef CBLAS_H
#define CBLAS_H
#ifdef __cplusplus
extern "C" {
#endif
typedef enum CBLAS_ORDER { CblasRowMajor = 101, CblasColMajor = 102 } CBLAS_ORDER;
typedef enum CBLAS_TRANSPOSE { CblasNoTrans = 111, CblasTrans = 112, CblasConjTrans = 113 } CBLAS_TRANSPOSE;
void cblas_sgemm(const CBLAS_ORDER Order, const CBLAS_TRANSPOSE TransA,
                 const CBLAS_TRANSPOSE TransB, const int M, const int N, const int K,
                 const float alpha, const float *A, const int lda,
                 const float *B, const int ldb, const float beta, float *C, const int ldc);
#ifdef __cplusplus
}
#endif
#endif
EOF
}
if [ -f "$PREFIX/lib/libopenblas.a" ]; then
  write_cblas_header
  echo "已有 $PREFIX/lib/libopenblas.a"
  exit 0
fi
if [ ! -d "$SRC/.git" ]; then
  git clone --depth 1 --branch "$TAG" https://github.com/OpenMathLib/OpenBLAS.git "$SRC"
fi
# 上次如果编过别的目标,对象文件不能混用。
make -C "$SRC" clean >/dev/null 2>&1 || true
make -C "$SRC" -j"${JOBS:-4}" \
  TARGET=ARMV8 \
  ONLY_CBLAS=1 \
  NOFORTRAN=1 \
  NO_SHARED=1 \
  NO_LAPACK=1 \
  NUM_THREADS=8 \
  USE_OPENMP=0 \
  CC="$CC" \
  AR="$AR" \
  RANLIB="$RANLIB" \
  HOSTCC=gcc
mkdir -p "$PREFIX/lib" "$PREFIX/include"
# NO_SHARED=1 时 install 会找不到 .so。静态库和头文件已经够用。
cp -a "$SRC"/libopenblas_armv8p-*.a "$PREFIX/lib/libopenblas.a"
write_cblas_header
echo "已放入 $PREFIX/lib/libopenblas.a"
