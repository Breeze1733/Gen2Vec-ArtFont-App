#!/usr/bin/env bash
# download-models.sh — 在 Linux 服务器上下载 AI 模型到 ComfyUI
#
# 用法:
#   ./download-models.sh                          # 默认目标: 脚本所在目录的 ComfyUI/models/
#   ./download-models.sh /path/to/ComfyUI          # 指定 ComfyUI 根目录
#   ./download-models.sh /path/to/ComfyUI --direct # 直连 huggingface.co（不走镜像）
#   PARALLEL=5 ./download-models.sh                # 5 个文件并行下载
#
# 环境变量:
#   PARALLEL    并行下载数（默认 3）
#   MAX_RETRIES 每个文件最大重试次数（默认 3）

set -euo pipefail

# ── 参数 ──
COMFYUI_DIR="${1:-$(dirname "$(readlink -f "$0")")}"
USE_MIRROR=true
if [[ "${2:-}" == "--direct" ]]; then
    USE_MIRROR=false
fi

# ── 路径 ──
MODELS_DIR="$COMFYUI_DIR/models"
PARALLEL="${PARALLEL:-3}"
MAX_RETRIES="${MAX_RETRIES:-3}"

# ── 镜像选择 ──
if $USE_MIRROR; then
    HF_BASE="https://hf-mirror.com"
else
    HF_BASE="https://huggingface.co"
fi

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
GRAY='\033[0;90m'
NC='\033[0m'

echo "============================================"
echo "  ComfyUI 模型下载脚本"
echo "  目标目录: $MODELS_DIR"
echo "  镜像: $HF_BASE"
echo "  并行数: $PARALLEL"
echo "============================================"
echo ""

# ── 检查 ComfyUI ──
if [[ ! -f "$COMFYUI_DIR/main.py" ]]; then
    echo -e "${RED}❌ 错误：未找到 ComfyUI/main.py${NC}"
    echo "   请指定正确的 ComfyUI 根目录: $0 /path/to/ComfyUI"
    exit 2
fi
echo -e "${GREEN}✓${NC} ComfyUI 已检测到"

# ── 模型清单 ──
declare -A MODEL_URLS MODEL_SIZES MODEL_SUBDIRS
MODEL_LIST=(
    "z_image_turbo_bf16.safetensors"
    "flux1-schnell-fp8-e4m3fn.safetensors"
    "qwen_2.5_vl_7b_fp8_scaled.safetensors"
    "qwen-image-2512-Q3_K_M.gguf"
    "qwen_3_4b.safetensors"
    "t5xxl_fp8_e4m3fn.safetensors"
    "Qwen-Image-Lightning-4steps-V1.0.safetensors"
    "ae.safetensors"
    "qwen_image_vae.safetensors"
    "clip_l.safetensors"
)

MODEL_SUBDIRS["z_image_turbo_bf16.safetensors"]="diffusion_models"
MODEL_SUBDIRS["flux1-schnell-fp8-e4m3fn.safetensors"]="unet"
MODEL_SUBDIRS["qwen_2.5_vl_7b_fp8_scaled.safetensors"]="text_encoders"
MODEL_SUBDIRS["qwen-image-2512-Q3_K_M.gguf"]="diffusion_models"
MODEL_SUBDIRS["qwen_3_4b.safetensors"]="text_encoders"
MODEL_SUBDIRS["t5xxl_fp8_e4m3fn.safetensors"]="clip"
MODEL_SUBDIRS["Qwen-Image-Lightning-4steps-V1.0.safetensors"]="loras"
MODEL_SUBDIRS["ae.safetensors"]="vae"
MODEL_SUBDIRS["qwen_image_vae.safetensors"]="vae"
MODEL_SUBDIRS["clip_l.safetensors"]="clip"

MODEL_URLS["z_image_turbo_bf16.safetensors"]="$HF_BASE/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors"
MODEL_URLS["flux1-schnell-fp8-e4m3fn.safetensors"]="$HF_BASE/Kijai/flux-fp8/resolve/main/flux1-schnell-fp8-e4m3fn.safetensors"
MODEL_URLS["qwen_2.5_vl_7b_fp8_scaled.safetensors"]="$HF_BASE/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"
MODEL_URLS["qwen-image-2512-Q3_K_M.gguf"]="$HF_BASE/unsloth/Qwen-Image-2512-GGUF/resolve/main/qwen-image-2512-Q3_K_M.gguf"
MODEL_URLS["qwen_3_4b.safetensors"]="$HF_BASE/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors"
MODEL_URLS["t5xxl_fp8_e4m3fn.safetensors"]="$HF_BASE/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors"
MODEL_URLS["Qwen-Image-Lightning-4steps-V1.0.safetensors"]="$HF_BASE/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Lightning-4steps-V1.0.safetensors"
MODEL_URLS["ae.safetensors"]="$HF_BASE/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors"
MODEL_URLS["qwen_image_vae.safetensors"]="$HF_BASE/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors"
MODEL_URLS["clip_l.safetensors"]="$HF_BASE/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors"

# ── 下载单个文件的函数 ──
download_one() {
    local filename="$1"
    local subdir="${MODEL_SUBDIRS[$filename]}"
    local url="${MODEL_URLS[$filename]}"
    local dest_dir="$MODELS_DIR/$subdir"
    local dest_file="$dest_dir/$filename"

    mkdir -p "$dest_dir"

    if [[ -f "$dest_file" ]]; then
        local size; size=$(du -h "$dest_file" | cut -f1)
        echo -e "${GRAY}⏭ $filename ($size) — 已存在，跳过${NC}"
        return 0  # skip
    fi

    echo -e "${YELLOW}⬇ $subdir/$filename${NC}"

    local attempt=1
    while [[ $attempt -le $MAX_RETRIES ]]; do
        if curl -fL --progress-bar -o "$dest_file" "$url"; then
            local actual_size; actual_size=$(du -h "$dest_file" | cut -f1)
            echo -e "${GREEN}   ✅ 完成 ($actual_size)${NC}"
            return 1  # ok
        fi

        if [[ $attempt -lt $MAX_RETRIES ]]; then
            echo -e "   ⚠ 重试 $attempt/$MAX_RETRIES..."
            sleep 5
        else
            echo -e "${RED}   ❌ 失败（已重试 $MAX_RETRIES 次）${NC}"
            return 2  # error
        fi
        ((attempt++))
    done
}

# ── 并行下载调度 ──
echo ""
echo "共 ${#MODEL_LIST[@]} 个文件，$PARALLEL 个并行下载"
echo ""

ok=0; skip=0; fail=0
running=0
pids=()

for filename in "${MODEL_LIST[@]}"; do
    # 等待直到有空位
    while [[ $running -ge $PARALLEL ]]; do
        for i in "${!pids[@]}"; do
            if ! kill -0 "${pids[$i]}" 2>/dev/null; then
                wait "${pids[$i]}" && ret=$? || ret=$?
                case $ret in
                    0) ((skip++)) ;;
                    1) ((ok++)) ;;
                    *) ((fail++)) ;;
                esac
                unset "pids[$i]"
                pids=("${pids[@]}")  # re-index
                ((running--))
            fi
        done
        sleep 0.5
    done

    # 启动一个新的后台下载
    download_one "$filename" &
    pids+=($!)
    ((running++))
done

# 等待剩余的全部完成
for pid in "${pids[@]}"; do
    wait "$pid" && ret=$? || ret=$?
    case $ret in
        0) ((skip++)) ;;
        1) ((ok++)) ;;
        *) ((fail++)) ;;
    esac
done

# ── 结果 ──
echo ""
echo "============================================"
if [[ $fail -gt 0 ]]; then
    echo -e "  ⚠ $ok 成功, $skip 跳过, $fail 失败"
    echo "  重新运行脚本重试失败的文件"
else
    echo -e "  ${GREEN}✅ 完成！$ok 下载, $skip 跳过${NC}"
fi
echo "============================================"

[[ $fail -gt 0 ]] && exit 1
exit 0
