#!/usr/bin/env bash
# download-models.sh - download AI models into ComfyUI with resumable downloads.
#
# Usage:
#   ./download-models.sh                          # target: current directory (ComfyUI root)
#   ./download-models.sh /path/to/ComfyUI          # target: specified ComfyUI root
#   ./download-models.sh /path/to/ComfyUI --direct # use huggingface.co instead of hf-mirror.com
#   PARALLEL=5 ./download-models.sh                # download 5 files concurrently
#   DEBUG=1 ./download-models.sh                   # print commands while running
#
# Environment:
#   PARALLEL      concurrent file downloads, default 3
#   MAX_RETRIES   retry attempts per file, default 3
#   ARIA2C_CONNS  aria2c connections per file, default 4
#   KEEP_ARIA2_CONTROL=1 keep old .aria2 control files beside partial downloads
#
# If Linux reports a bad interpreter error, fix Windows line endings first:
#   sed -i 's/\r$//' download-models.sh

SCRIPT_PATH="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/$(basename "$0")"
if [[ -r "$SCRIPT_PATH" ]] && grep -q $'\r' "$SCRIPT_PATH" 2>/dev/null; then
    echo "ERROR: Windows CRLF line endings detected."
    echo "Run: sed -i 's/\r$//' $(basename "$0")"
    exit 1
fi

set -euo pipefail

if [[ "${DEBUG:-0}" != "0" ]]; then
    set -x
fi

USE_MIRROR=true
COMFYUI_DIR=""

for arg in "$@"; do
    case "$arg" in
        --direct)
            USE_MIRROR=false
            ;;
        --help|-h)
            sed -n '2,18p' "$0"
            exit 0
            ;;
        *)
            if [[ -z "$COMFYUI_DIR" ]]; then
                COMFYUI_DIR="$arg"
            fi
            ;;
    esac
done

COMFYUI_DIR="${COMFYUI_DIR:-$(pwd)}"
if [[ -d "$COMFYUI_DIR" ]]; then
    COMFYUI_DIR="$(cd "$COMFYUI_DIR" 2>/dev/null && pwd)"
else
    echo "ERROR: directory does not exist: $COMFYUI_DIR"
    exit 2
fi

MODELS_DIR="$COMFYUI_DIR/models"
PARALLEL="${PARALLEL:-3}"
MAX_RETRIES="${MAX_RETRIES:-3}"
ARIA2C_CONNS="${ARIA2C_CONNS:-4}"
KEEP_ARIA2_CONTROL="${KEEP_ARIA2_CONTROL:-0}"

if $USE_MIRROR; then
    HF_BASE="https://hf-mirror.com"
else
    HF_BASE="https://huggingface.co"
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
BOLD='\033[1m'
NC='\033[0m'

DOWNLOADER=""
DOWNLOADER_NAME=""
if command -v aria2c &>/dev/null; then
    DOWNLOADER="aria2c"
    DOWNLOADER_NAME="aria2c (multi-connection, resumable)"
elif command -v curl &>/dev/null; then
    DOWNLOADER="curl"
    DOWNLOADER_NAME="curl (single-connection, resumable)"
else
    echo -e "${RED}ERROR: aria2c or curl is required.${NC}"
    exit 1
fi

echo "============================================"
echo "  ComfyUI model downloader"
echo "  ComfyUI:      $COMFYUI_DIR"
echo "  Models dir:   $MODELS_DIR"
echo "  Source:       $HF_BASE"
echo "  Downloader:   $DOWNLOADER_NAME"
echo "  Parallel:     $PARALLEL"
if [[ "$DOWNLOADER" == "aria2c" ]]; then
    echo "  Connections:  $ARIA2C_CONNS per file"
fi
echo "============================================"
echo ""

if [[ ! -f "$COMFYUI_DIR/main.py" ]]; then
    echo -e "${RED}ERROR: $COMFYUI_DIR/main.py was not found.${NC}"
    echo "Please run this script inside ComfyUI, or pass the ComfyUI root directory:"
    echo "  $0 /path/to/ComfyUI"
    exit 2
fi
echo -e "${GREEN}OK${NC} ComfyUI detected"
echo ""

# Format: filename|subdir|url
MODEL_ENTRIES=(
    "z_image_turbo_bf16.safetensors|diffusion_models|$HF_BASE/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors"
    "flux1-schnell-fp8-e4m3fn.safetensors|unet|$HF_BASE/Kijai/flux-fp8/resolve/main/flux1-schnell-fp8-e4m3fn.safetensors"
    "qwen_2.5_vl_7b_fp8_scaled.safetensors|text_encoders|$HF_BASE/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"
    "qwen-image-2512-Q3_K_M.gguf|diffusion_models|$HF_BASE/unsloth/Qwen-Image-2512-GGUF/resolve/main/qwen-image-2512-Q3_K_M.gguf"
    "qwen_3_4b.safetensors|text_encoders|$HF_BASE/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors"
    "t5xxl_fp8_e4m3fn.safetensors|clip|$HF_BASE/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors"
    "Qwen-Image-Lightning-4steps-V1.0.safetensors|loras|$HF_BASE/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Lightning-4steps-V1.0.safetensors"
    "ae.safetensors|vae|$HF_BASE/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors"
    "qwen_image_vae.safetensors|vae|$HF_BASE/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors"
    "clip_l.safetensors|clip|$HF_BASE/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors"
)

get_filename() {
    local entry="$1"
    echo "${entry%%|*}"
}

get_subdir() {
    local entry="$1"
    local rest="${entry#*|}"
    echo "${rest%%|*}"
}

get_url() {
    local entry="$1"
    local rest="${entry#*|}"
    echo "${rest#*|}"
}

get_local_size() {
    local file="$1"
    wc -c < "$file" 2>/dev/null | tr -d '[:space:]'
}

get_remote_size() {
    local url="$1"

    if ! command -v curl &>/dev/null || ! command -v awk &>/dev/null; then
        echo ""
        return 0
    fi

    curl -fsIL --connect-timeout 20 --max-time 60 "$url" 2>/dev/null \
        | awk 'BEGIN { IGNORECASE=1 } /^Content-Length:/ { size=$2 } END { gsub("\r", "", size); print size }'
}

PROGRESS_DIR=$(mktemp -d "/tmp/model-dl-XXXXXX" 2>/dev/null || mktemp -d -t model-dl-XXXXXX 2>/dev/null || {
    fallback="/tmp/model-dl-$$"
    mkdir -p "$fallback"
    echo "$fallback"
})

cleanup() {
    rm -rf "$PROGRESS_DIR"
}
trap cleanup EXIT INT TERM

export MODELS_DIR DOWNLOADER MAX_RETRIES ARIA2C_CONNS KEEP_ARIA2_CONTROL PROGRESS_DIR

download_one() {
    set +e

    local entry="$1"
    local filename subdir url dest_dir dest_file aria2_file complete_file status_file progress_file error_log

    filename="$(get_filename "$entry")"
    subdir="$(get_subdir "$entry")"
    url="$(get_url "$entry")"
    dest_dir="$MODELS_DIR/$subdir"
    dest_file="$dest_dir/$filename"
    aria2_file="$dest_file.aria2"
    complete_file="$dest_file.complete"
    status_file="$PROGRESS_DIR/$filename.status"
    progress_file="$PROGRESS_DIR/$filename.progress"
    error_log="$PROGRESS_DIR/$filename.error"

    if ! mkdir -p "$dest_dir" 2>/dev/null; then
        echo "FAIL|mkdir_failed" > "$status_file"
        echo "mkdir failed: $dest_dir" >> "$error_log"
        return 1
    fi

    # Only a previous successful run creates this marker. A partial file alone is resumable,
    # not skippable.
    if [[ -f "$dest_file" && -f "$complete_file" ]]; then
        local size
        size=$(du -h "$dest_file" 2>/dev/null | cut -f1)
        echo "SKIP|${size:-?}" > "$status_file"
        return 0
    fi

    if [[ -f "$dest_file" ]]; then
        local local_bytes remote_bytes partial_size
        local_bytes="$(get_local_size "$dest_file")"
        remote_bytes="$(get_remote_size "$url")"

        if [[ -n "$remote_bytes" && "$local_bytes" == "$remote_bytes" ]]; then
            touch "$complete_file"
            partial_size=$(du -h "$dest_file" 2>/dev/null | cut -f1)
            echo "SKIP|${partial_size:-?}" > "$status_file"
            echo "local file already matches remote size: $dest_file" >> "$error_log"
            return 0
        fi

        if [[ "$KEEP_ARIA2_CONTROL" != "1" && -f "$aria2_file" ]]; then
            mv "$aria2_file" "$aria2_file.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null
            echo "old aria2 control file was backed up before resume: $aria2_file" >> "$error_log"
        fi

        partial_size=$(du -h "$dest_file" 2>/dev/null | cut -f1)
        echo "RESUMING|${partial_size:-?}|$(date +%s)" > "$status_file"
        if [[ -n "$remote_bytes" ]]; then
            echo "resuming partial file: $dest_file ($local_bytes/$remote_bytes bytes)" >> "$error_log"
        else
            echo "resuming existing file without remote size check: $dest_file" >> "$error_log"
        fi
    else
        echo "DOWNLOADING|0|$(date +%s)" > "$status_file"
    fi
    echo "url: $url" >> "$error_log"

    local attempt=1 ret_code=0
    while [[ $attempt -le $MAX_RETRIES ]]; do
        ret_code=0

        if [[ "$DOWNLOADER" == "aria2c" ]]; then
            aria2c \
                --continue=true \
                --auto-file-renaming=false \
                --allow-overwrite=true \
                --split="$ARIA2C_CONNS" \
                --min-split-size=1M \
                --max-connection-per-server="$ARIA2C_CONNS" \
                --file-allocation=none \
                --console-log-level=notice \
                --summary-interval=0 \
                --dir="$dest_dir" \
                --out="$filename" \
                "$url" 2>&1 | while IFS= read -r line; do
                    if [[ "$line" =~ ^\[#[a-f0-9]+ ]]; then
                        echo "$line" > "$progress_file"
                    fi
                    echo "$line" >> "$error_log"
                done
            ret_code=${PIPESTATUS[0]}
        else
            curl -fL --progress-bar \
                --retry 0 \
                --connect-timeout 30 \
                --max-time 0 \
                -C - \
                -o "$dest_file" \
                "$url" 2>&1 | while IFS= read -r line; do
                    echo "$line" > "$progress_file"
                    echo "$line" >> "$error_log"
                done
            ret_code=${PIPESTATUS[0]}
        fi

        echo "attempt=$attempt exit_code=$ret_code file_exists=$(test -f "$dest_file" && echo yes || echo no)" >> "$error_log"

        if [[ $ret_code -eq 0 && -f "$dest_file" ]]; then
            touch "$complete_file"
            local actual_size
            actual_size=$(du -h "$dest_file" 2>/dev/null | cut -f1)
            echo "OK|${actual_size:-?}" > "$status_file"
            return 0
        fi

        if [[ $attempt -lt $MAX_RETRIES ]]; then
            echo "RETRY|$attempt|$MAX_RETRIES" > "$status_file"
            sleep 3
            if [[ -f "$dest_file" ]]; then
                local retry_size
                retry_size=$(du -h "$dest_file" 2>/dev/null | cut -f1)
                echo "RESUMING|${retry_size:-?}|$(date +%s)" > "$status_file"
            else
                echo "DOWNLOADING|0|$(date +%s)" > "$status_file"
            fi
        fi

        attempt=$((attempt + 1))
    done

    # Keep partial files and .aria2 control files so the next run can continue.
    echo "FAIL" > "$status_file"
    echo "failed after $MAX_RETRIES attempts; partial file kept for resume" >> "$error_log"
    return 1
}

monitor_progress() {
    set +e
    local total=${#MODEL_ENTRIES[@]}

    sleep 1

    while true; do
        printf "\033[2J\033[H" 2>/dev/null || true

        local now done_count=0 skip_count=0 fail_count=0 active_count=0
        now=$(date +%s)

        echo -e "${BOLD}--- Download progress ---${NC}"
        echo ""

        local entry filename subdir label status_file progress_file status_line status arg1 arg2
        for entry in "${MODEL_ENTRIES[@]}"; do
            filename="$(get_filename "$entry")"
            subdir="$(get_subdir "$entry")"
            label="$subdir/$filename"
            status_file="$PROGRESS_DIR/$filename.status"
            progress_file="$PROGRESS_DIR/$filename.progress"

            if [[ ! -f "$status_file" ]]; then
                echo -e "  ${GRAY}WAIT $label${NC}"
                continue
            fi

            status_line=$(head -1 "$status_file")
            IFS='|' read -r status arg1 arg2 <<< "$status_line"

            case "$status" in
                SKIP)
                    echo -e "  ${GRAY}SKIP $label - already complete ($arg1)${NC}"
                    skip_count=$((skip_count + 1))
                    ;;
                OK)
                    echo -e "  ${GREEN}OK   $label - complete ($arg1)${NC}"
                    done_count=$((done_count + 1))
                    ;;
                FAIL)
                    echo -e "  ${RED}FAIL $label - partial file kept${NC}"
                    fail_count=$((fail_count + 1))
                    ;;
                RETRY)
                    echo -e "  ${YELLOW}RETRY $label ($arg1/$arg2)${NC}"
                    active_count=$((active_count + 1))
                    ;;
                DOWNLOADING|RESUMING)
                    local elapsed elapsed_str prog_info verb
                    elapsed=$(( now - arg2 ))
                    if [[ $elapsed -ge 3600 ]]; then
                        elapsed_str="$((elapsed/3600))h$(((elapsed%3600)/60))m"
                    elif [[ $elapsed -ge 60 ]]; then
                        elapsed_str="$((elapsed/60))m$((elapsed%60))s"
                    else
                        elapsed_str="${elapsed}s"
                    fi
                    prog_info=""
                    if [[ -f "$progress_file" ]]; then
                        prog_info=$(tail -1 "$progress_file" 2>/dev/null | head -c 60)
                    fi
                    verb="DOWN"
                    [[ "$status" == "RESUMING" ]] && verb="RESUME"
                    echo -e "  ${CYAN}$verb $label [$elapsed_str]${NC} ${GRAY}${prog_info}${NC}"
                    active_count=$((active_count + 1))
                    ;;
            esac
        done

        echo ""
        echo -e "${BOLD}Summary: ${GREEN}$done_count done${NC} | ${GRAY}$skip_count skipped${NC} | ${CYAN}$active_count active${NC} | ${RED}$fail_count failed${NC} | $total total${NC}"

        local processed=$((done_count + skip_count + fail_count))
        if [[ $processed -ge $total ]]; then
            echo ""
            break
        fi

        sleep 1
    done
}

collect_finished_job() {
    local pid fn sf s
    for pid in "${!JOB_PIDS[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
            fn="${JOB_PIDS[$pid]}"
            sf="$PROGRESS_DIR/$fn.status"
            if [[ -f "$sf" ]]; then
                s=$(head -1 "$sf" | cut -d'|' -f1) || true
                case "$s" in
                    OK) ok=$((ok + 1)) ;;
                    SKIP) skip=$((skip + 1)) ;;
                    *) fail=$((fail + 1)) ;;
                esac
            else
                fail=$((fail + 1))
            fi
            unset "JOB_PIDS[$pid]"
            running=$((running - 1))
            return 0
        fi
    done
    return 1
}

echo ""
echo "Start downloading ${#MODEL_ENTRIES[@]} files ..."
echo ""

monitor_progress &
MONITOR_PID=$!

ok=0
skip=0
fail=0
running=0
declare -A JOB_PIDS

for entry in "${MODEL_ENTRIES[@]}"; do
    while [[ $running -ge $PARALLEL ]]; do
        wait -n 2>/dev/null || true
        collect_finished_job || true
    done

    fname="$(get_filename "$entry")"
    download_one "$entry" &
    pid=$!
    JOB_PIDS[$pid]="$fname"
    running=$((running + 1))
done

while [[ $running -gt 0 ]]; do
    wait -n 2>/dev/null || true
    collect_finished_job || true
done

wait "$MONITOR_PID" 2>/dev/null || true

echo "============================================"
if [[ $fail -gt 0 ]]; then
    echo -e "  ${YELLOW}Finished with failures:${NC} ${GREEN}$ok downloaded${NC}, ${GRAY}$skip skipped${NC}, ${RED}$fail failed${NC}"
    echo ""
    echo "  Failed files:"

    for entry in "${MODEL_ENTRIES[@]}"; do
        fname="$(get_filename "$entry")"
        sf="$PROGRESS_DIR/$fname.status"
        if [[ -f "$sf" ]]; then
            s=$(head -1 "$sf" | cut -d'|' -f1) || true
            if [[ "$s" == "FAIL" ]]; then
                echo -e "    ${RED}x${NC} $(get_subdir "$entry")/$fname"
            fi
        fi
    done

    echo ""
    echo "  Partial files are kept. Re-run this script to resume them."
else
    echo -e "  ${GREEN}All done:${NC} $ok downloaded, $skip skipped"
fi
echo "============================================"

[[ $fail -gt 0 ]] && exit 1
exit 0
