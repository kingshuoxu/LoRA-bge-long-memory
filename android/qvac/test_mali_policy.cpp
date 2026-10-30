#include "mali_vulkan_policy.h"

#include <cstdio>
#include <cstring>

static int failures = 0;

static void expect(bool cond, const char * message) {
    if (!cond) {
        std::fprintf(stderr, "FAIL %s\n", message);
        failures++;
    }
}

static void expect_u32(uint32_t got, uint32_t want, const char * message) {
    if (got != want) {
        std::fprintf(stderr, "FAIL %s got %u want %u\n", message, got, want);
        failures++;
    }
}

int main() {
    expect(!lorabge_vk_is_arm_vendor(LORABGE_VK_VENDOR_ID_QUALCOMM), "Adreno vendor stays out of the Mali branch");
    expect(!lorabge_vk_is_arm_vendor(0x1002u), "AMD is not Mali");
    expect(lorabge_vk_is_arm_vendor(LORABGE_VK_VENDOR_ID_ARM), "ARM 0x13B5 is Mali");

    expect(lorabge_mali_enable_fp16(true, true, true), "fp16 storage and arithmetic stay on");
    expect(!lorabge_mali_enable_fp16(true, true, false), "missing shaderFloat16 keeps fp32");
    expect(!lorabge_mali_enable_fp16(true, false, true), "missing fp16 compute keeps fp32");
    expect(!lorabge_mali_enable_fp16(false, true, true), "missing fp16 storage keeps fp32");
    expect(!lorabge_mali_enable_bf16(true), "bf16 is off even when the device reports it");
    expect(!lorabge_mali_enable_coopmat(true), "cooperative matrix is off");
    expect(!lorabge_mali_enable_coopmat2(true), "cooperative matrix 2 is off");

    expect(lorabge_mali_suballocation_bytes(1024ull << 20, 2048ull << 20, 2048ull << 20) == LORABGE_MALI_SUBALLOC_CAP,
           "suballocation is capped at 256MB");
    expect(lorabge_mali_suballocation_bytes(LORABGE_MALI_SUBALLOC_CAP, 64ull << 20, 1024ull << 20) == (64ull << 20),
           "suballocation respects maxMemoryAllocationSize");
    expect(lorabge_mali_suballocation_bytes(LORABGE_MALI_SUBALLOC_CAP, 1024ull << 20, 32ull << 20) == (32ull << 20),
           "suballocation respects max buffer size");

    expect(lorabge_mali_descriptor_limit_ok(24, 12), "24 storage buffers is enough");
    expect(!lorabge_mali_descriptor_limit_ok(8, 12), "8 storage buffers is not enough");
    expect(lorabge_mali_descriptor_limit_ok(0, 12), "an unqueried limit does not fail the device");

    uint32_t x = 0, y = 0;
    lorabge_mali_workgroup(16, &x, &y);
    expect_u32(x, 64, "subgroup 16 medium tile x");
    expect_u32(y, 64, "subgroup 16 medium tile y");
    lorabge_mali_workgroup(128, &x, &y);
    expect_u32(x, 128, "large subgroup grows the tile");

    uint32_t small_mmq[11] = {32, 32, 32, 32, 32, 32, 2, 2, 1, 1, 16};
    lorabge_mali_retile(small_mmq, 11, 16);
    expect_u32(small_mmq[10], 16, "small quant WARP stays 16");
    expect_u32(small_mmq[0], 16, "small quant BLOCK is not promoted to 32");
    expect_u32(small_mmq[4], 32, "small quant WM is two subgroups");
    expect_u32(small_mmq[1], 32, "BM is left alone so the dispatch denom still matches");

    uint32_t f16_small[11] = {16, 32, 32, 16, 32, 32, 2, 2, 2, 1, 16};
    lorabge_mali_retile(f16_small, 11, 16);
    expect_u32(f16_small[0], 16, "f16 small BLOCK stays one subgroup");
    expect_u32(f16_small[10], 16, "f16 small WARP");

    uint32_t medium[11] = {128, 64, 64, 16, 16, 32, 2, 4, 2, 1, 16};
    lorabge_mali_retile(medium, 11, 16);
    expect_u32(medium[4], 32, "medium WM becomes 2*subgroup");
    expect_u32(medium[10], 16, "medium WARP");
    expect_u32(medium[0], 128, "medium BLOCK stays a multiple of the subgroup");
    expect_u32(medium[1], 64, "medium BM stays 64");

    uint32_t adreno_like[11] = {128, 128, 128, 16, 64, 64, 2, 4, 4, 1, 64};
    uint32_t copy[11];
    std::memcpy(copy, adreno_like, sizeof(copy));
    if (!lorabge_vk_is_arm_vendor(LORABGE_VK_VENDOR_ID_QUALCOMM)) {
        // The Adreno call site does not retile. This locks the guard itself.
    } else {
        lorabge_mali_retile(copy, 11, 64);
    }
    expect(std::memcmp(copy, adreno_like, sizeof(copy)) == 0, "Adreno tile is not retiled");

    expect(std::strcmp(LORABGE_VK_CAPS_PREFIX, "ggml_vulkan: caps ") == 0, "caps log prefix");
    expect(lorabge_quote_vk("Mali\"G925\n") == "Mali G925 ", "quotes and newlines are flattened");

    if (failures != 0) {
        std::fprintf(stderr, "%d checks failed\n", failures);
        return 1;
    }
    std::printf("mali vulkan policy ok\n");
    return 0;
}
