#pragma once
// Runtime Vulkan policy for ARM Mali / Immortalis (vendor 0x13B5).
// Adreno is 0x5143 and must not enter these branches.
// The numbers come from llama.cpp PR 18493 (Gong-Mi, Mali-G720),
// tetherto/qvac-ext-ggml issue 34, and qvac-ext-ggml PR 28 (Mali-G715):
// cooperative matrix on Mali is slower and the subgroup is 16, so tiles
// that assume a warp of 32 overrun. bf16 is off. fp16 storage and
// arithmetic stay on when the device actually has both.

#include <cstdint>
#include <string>

inline constexpr uint32_t LORABGE_VK_VENDOR_ID_ARM = 0x13B5u;
inline constexpr uint32_t LORABGE_VK_VENDOR_ID_QUALCOMM = 0x5143u;
inline constexpr uint64_t LORABGE_MALI_SUBALLOC_CAP = 256ull * 1024ull * 1024ull;
inline constexpr const char * LORABGE_VK_CAPS_PREFIX = "ggml_vulkan: caps ";

inline bool lorabge_vk_is_arm_vendor(uint32_t vendor_id) {
    return vendor_id == LORABGE_VK_VENDOR_ID_ARM;
}

// fp16 storage (16-bit buffer types) and fp16 arithmetic (shaderFloat16).
// Both are required. A device that only has one of them stays on fp32.
inline bool lorabge_mali_enable_fp16(bool storage, bool compute, bool shader_float16) {
    return storage && compute && shader_float16;
}

// Mali coopmat and bf16 are not used. The caller still passes the device's
// reported bits so a test can show they are ignored.
inline bool lorabge_mali_enable_bf16(bool device_bf16) {
    (void) device_bf16;
    return false;
}

inline bool lorabge_mali_enable_coopmat(bool device_coopmat) {
    (void) device_coopmat;
    return false;
}

inline bool lorabge_mali_enable_coopmat2(bool device_coopmat2) {
    (void) device_coopmat2;
    return false;
}

// Suballocation stays inside the driver limits and under 256MB.
// A zero reported limit means "unknown" and does not raise the cap.
inline uint64_t lorabge_mali_suballocation_bytes(uint64_t requested, uint64_t max_alloc, uint64_t max_buffer) {
    uint64_t out = requested == 0 ? LORABGE_MALI_SUBALLOC_CAP : requested;
    if (out > LORABGE_MALI_SUBALLOC_CAP) {
        out = LORABGE_MALI_SUBALLOC_CAP;
    }
    if (max_alloc > 0 && out > max_alloc) {
        out = max_alloc;
    }
    if (max_buffer > 0 && out > max_buffer) {
        out = max_buffer;
    }
    return out;
}

// Matmul shaders bind MAX_PARAMETER_COUNT storage buffers in one stage.
// A reported 0 means the limit was not queried.
inline bool lorabge_mali_descriptor_limit_ok(uint32_t max_per_stage_storage_buffers, uint32_t needed) {
    if (max_per_stage_storage_buffers == 0) {
        return true;
    }
    return max_per_stage_storage_buffers >= needed;
}

// Medium tile used once the 128x128 large tile is declined.
// Subgroup 16 stays on 64x64. A subgroup above 64 grows the tile with it.
inline void lorabge_mali_workgroup(uint32_t subgroup, uint32_t * x, uint32_t * y) {
    uint32_t sg = subgroup < 8u ? 16u : subgroup;
    if (sg > 64u) {
        *x = sg;
        *y = sg;
        return;
    }
    *x = 64u;
    *y = 64u;
}

// Spec constants are {BLOCK, BM, BN, BK, WM, WN, WMITER, TM, TN, TK, WARP}.
// WARP follows the real subgroup. A subgroup of 16 must not be promoted to 32.
// WM is two subgroups when that still fits in BM.
// The small quant tile's BLOCK of 32 is one extra subgroup on Mali and is snapped back.
inline void lorabge_mali_retile(uint32_t * tile, uint32_t count, uint32_t subgroup) {
    if (tile == nullptr || count < 11u || subgroup < 8u) {
        return;
    }
    tile[10] = subgroup;
    const uint32_t wm = subgroup * 2u;
    if (tile[1] >= wm) {
        tile[4] = wm;
    } else if (tile[1] >= subgroup) {
        tile[4] = subgroup;
    }
    if (tile[0] < subgroup) {
        tile[0] = subgroup;
    } else if ((tile[0] % subgroup) != 0u) {
        uint32_t snapped = (tile[0] / subgroup) * subgroup;
        tile[0] = snapped < subgroup ? subgroup : snapped;
    }
    if (subgroup < 32u && tile[0] == 32u && tile[1] <= 32u && tile[2] <= 32u) {
        tile[0] = subgroup;
    }
}

inline std::string lorabge_quote_vk(const std::string & text) {
    std::string out;
    out.reserve(text.size());
    for (char c : text) {
        if (c == '"' || c == '\n' || c == '\r') {
            out.push_back(' ');
        } else {
            out.push_back(c);
        }
    }
    return out;
}
