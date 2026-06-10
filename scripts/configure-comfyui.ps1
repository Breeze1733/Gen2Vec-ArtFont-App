# configure-comfyui.ps1 - ComfyUI post-install configuration.
<#
.SYNOPSIS
Applies patched custom-node files and installs required Python packages
into a ComfyUI Windows portable installation.

Call this AFTER download-comfyui-engine.ps1 has finished.  The engine
download script already calls this script as its final step (step 6).

Sources for embedded patches:
    services/txt2img-api/custom_nodes/comfyui-inspyrenet-rembg/
When the source patches are updated, synchronise the embedded here-strings.

.PARAMETER DestDir
Target backend directory (the folder that contains
ComfyUI_windows_portable_nvidia). Defaults to the script directory.

.PARAMETER Electron
Electron integration mode: prints COMFYCFG: structured progress lines.

.EXAMPLE
.\configure-comfyui.ps1
.\configure-comfyui.ps1 -DestDir D:\ArtFont
.\configure-comfyui.ps1 -Electron -DestDir .\backend\
#>

param(
    [string]$DestDir = $PSScriptRoot,
    [switch]$Electron
)

$ErrorActionPreference = "Stop"
$PREFIX = if ($Electron) { "COMFYCFG:" } else { "" }

# -- paths --
$ComfyPortable   = Join-Path $DestDir "ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable"
$ComfyMain       = Join-Path $ComfyPortable "ComfyUI\main.py"
$CustomNodesDir  = Join-Path $ComfyPortable "ComfyUI\custom_nodes"
$PythonExe       = Join-Path $ComfyPortable "python_embeded\python.exe"
$InspyNodeDir    = Join-Path $CustomNodesDir "comfyui-inspyrenet-rembg"
$PatchSentinel   = Join-Path $InspyNodeDir ".patches-applied"
$PipSentinel     = Join-Path $ComfyPortable ".pip-complete"

# -- embedded patched __init__.py --
$PatchedInitPy = @'
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from Inspyrenet_Rembg import InspyrenetRembg, InspyrenetRembgAdvanced

NODE_CLASS_MAPPINGS = {
    "InspyrenetRembg" : InspyrenetRembg,
    "InspyrenetRembgAdvanced" : InspyrenetRembgAdvanced,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "InspyrenetRembg": "Inspyrenet Rembg",
    "InspyrenetRembgAdvanced": "Inspyrenet Rembg Advanced"
}
__all__ = ['NODE_CLASS_MAPPINGS', "NODE_DISPLAY_NAME_MAPPINGS"]
'@

# -- embedded patched Inspyrenet_Rembg.py --
$PatchedInspyrenetRembgPy = @'
import os
import numpy as np
import torch
from PIL import Image

# ======================================================================
# Env vars + numba monkey-patch MUST run before importing
# transparent_background.  Otherwise numba writes inline cache into
# site-packages __pycache__ with a path exceeding Windows MAX_PATH
# (260 chars), causing FileNotFoundError.
# ======================================================================
_CUSTOM_NODE_DIR = os.path.dirname(os.path.abspath(__file__))
_COMFYUI_DIR = os.path.dirname(os.path.dirname(_CUSTOM_NODE_DIR))
_INSPYRENET_MODEL_DIR = os.path.join(_COMFYUI_DIR, "models", "inspyrenet")

# Model directory -- prevents first-run download from GitHub.
if "TRANSPARENT_BACKGROUND_FILE_PATH" not in os.environ:
    os.environ["TRANSPARENT_BACKGROUND_FILE_PATH"] = _INSPYRENET_MODEL_DIR

# numba cache directory (only affects explicit API cache, not pymatting inline cache).
if "NUMBA_CACHE_DIR" not in os.environ:
    os.environ["NUMBA_CACHE_DIR"] = os.path.join(_INSPYRENET_MODEL_DIR, ".numba_cache")

# == monkey-patch: disable numba inline file cache ==
# pymatting sources use @njit(cache=True) which writes to __pycache__/
# next to the source file.  That path easily exceeds Windows MAX_PATH.
# NUMBA_CACHE_DIR cannot redirect inline cache, so we must force
# cache=False on numba.njit/jit before any import.
# Side effect: JIT results are not persisted; recompiled on next restart.
try:
    import numba as _numba
    _orig_njit = _numba.njit
    _orig_jit = _numba.jit

    def _njit_nocache(*args, **kwargs):
        kwargs.pop("cache", None)
        return _orig_njit(*args, **kwargs, cache=False)

    def _jit_nocache(*args, **kwargs):
        kwargs.pop("cache", None)
        return _orig_jit(*args, **kwargs, cache=False)

    _numba.njit = _njit_nocache
    _numba.jit = _jit_nocache
except Exception:
    pass  # numba not available -- silently skip, transparent_background degrades

from transparent_background import Remover
from tqdm import tqdm


# Tensor to PIL
def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))

# Convert PIL to Tensor
def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

class InspyrenetRembg:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "torchscript_jit": (["default", "on"],)
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "remove_background"
    CATEGORY = "image"

    def remove_background(self, image, torchscript_jit):
        if (torchscript_jit == "default"):
            remover = Remover()
        else:
            remover = Remover(jit=True)
        img_list = []
        for img in tqdm(image, "Inspyrenet Rembg"):
            mid = remover.process(tensor2pil(img), type='rgba')
            out =  pil2tensor(mid)
            img_list.append(out)
        img_stack = torch.cat(img_list, dim=0)
        mask = img_stack[:, :, :, 3]
        return (img_stack, mask)

class InspyrenetRembgAdvanced:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
                "torchscript_jit": (["default", "on"],)
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "remove_background"
    CATEGORY = "image"

    def remove_background(self, image, torchscript_jit, threshold):
        if (torchscript_jit == "default"):
            remover = Remover()
        else:
            remover = Remover(jit=True)
        img_list = []
        for img in tqdm(image, "Inspyrenet Rembg"):
            mid = remover.process(tensor2pil(img), type='rgba', threshold=threshold)
            out =  pil2tensor(mid)
            img_list.append(out)
        img_stack = torch.cat(img_list, dim=0)
        mask = img_stack[:, :, :, 3]
        return (img_stack, mask)
'@

# -- helper functions --
function Emit {
    param([string]$Type, [string]$Message = "")
    if ($Electron) {
        if ($Message) { Write-Output "${PREFIX}${Type}|${Message}" }
        else { Write-Output "${PREFIX}${Type}" }
    }
}

function Write-Color {
    param([string]$Text, [string]$Color = "White")
    if (-not $Electron) { Write-Host $Text -ForegroundColor $Color }
}

function Write-Step {
    param([string]$Text)
    Write-Color "  $Text" DarkGray
}

function Finish-Ok {
    param([string]$Name, [string]$Detail = "")
    $msg = if ($Detail) { "${Name}|${Detail}" } else { $Name }
    Emit "DONE" $msg
    Write-Color "OK $Name $Detail" Green
}

function Finish-Skip {
    param([string]$Name, [string]$Detail = "")
    $msg = if ($Detail) { "${Name}|${Detail}" } else { $Name }
    Emit "SKIP" $msg
    Write-Color "Skip $Name $Detail" DarkGray
}

function Test-NonEmptyFile {
    param(
        [string]$Path,
        [long]$MinBytes = 1
    )
    if (-not (Test-Path $Path)) { return $false }
    try {
        $item = Get-Item -LiteralPath $Path
        return $item.PSIsContainer -eq $false -and $item.Length -ge $MinBytes
    } catch {
        return $false
    }
}

# -- main --
if (-not $Electron) {
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  ComfyUI configuration" -ForegroundColor White
    Write-Host "  Target: $DestDir" -ForegroundColor White
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
}

Emit "READY"
Emit "TOTAL" 2

$okCount = 0
$skipCount = 0
$failCount = 0

try {
    # -- pre-flight checks --
    if (-not (Test-NonEmptyFile $ComfyMain)) {
        throw "ComfyUI sentinel not found: $ComfyMain`nHas download-comfyui-engine.ps1 been run?"
    }
    if (-not (Test-NonEmptyFile $PythonExe -MinBytes (100 * 1024))) {
        throw "ComfyUI python_embeded not found: $PythonExe"
    }
    if (-not (Test-Path $InspyNodeDir)) {
        throw "Inspyrenet-Rembg custom node not found: $InspyNodeDir`nHas download-comfyui-engine.ps1 been run?"
    }

    # ================================================================
    # Step 1: Overwrite patched files.
    # ================================================================
    if (Test-NonEmptyFile $PatchSentinel) {
        Finish-Skip "apply_patches" "already applied"
        $skipCount++
    } else {
        Emit "START" "apply_patches|2 files -> comfyui-inspyrenet-rembg"
        Write-Color "Apply patched files" Yellow

        Write-Step "writing __init__.py"
        $initPyPath = Join-Path $InspyNodeDir "__init__.py"
        $PatchedInitPy | Set-Content -LiteralPath $initPyPath -Encoding UTF8
        if (-not (Test-NonEmptyFile $initPyPath)) { throw "failed to write __init__.py" }

        Write-Step "writing Inspyrenet_Rembg.py"
        $rembgPyPath = Join-Path $InspyNodeDir "Inspyrenet_Rembg.py"
        $PatchedInspyrenetRembgPy | Set-Content -LiteralPath $rembgPyPath -Encoding UTF8
        if (-not (Test-NonEmptyFile $rembgPyPath)) { throw "failed to write Inspyrenet_Rembg.py" }

        [void](New-Item -ItemType File -Force -Path $PatchSentinel)
        Finish-Ok "apply_patches" "2 files"
        $okCount++
    }

    # ================================================================
    # Step 2: pip install required packages.
    # ================================================================
    if (Test-NonEmptyFile $PipSentinel) {
        Finish-Skip "pip_install" "already installed"
        $skipCount++
    } else {
        $pipPkgs = "transparent-background gguf protobuf"
        Emit "START" "pip_install|$pipPkgs"
        Write-Color "pip install $pipPkgs" Yellow

        Write-Step "running: $PythonExe -m pip install $pipPkgs"
        if (-not $Electron) {
            # Manual mode: show live pip output.
            $pipProc = Start-Process -FilePath $PythonExe -ArgumentList @(
                "-m", "pip", "install", "transparent-background", "gguf", "protobuf"
            ) -NoNewWindow -Wait -PassThru
            if ($pipProc.ExitCode -ne 0) {
                throw "pip install failed with exit code $($pipProc.ExitCode)"
            }
        } else {
            # Electron mode: capture output to log, show tail on error.
            $pipLog = Join-Path $ComfyPortable "pip-install.log"
            $pipProc = Start-Process -FilePath $PythonExe -ArgumentList @(
                "-m", "pip", "install", "transparent-background", "gguf", "protobuf"
            ) -NoNewWindow -Wait -PassThru -RedirectStandardOutput $pipLog -RedirectStandardError $pipLog
            if ($pipProc.ExitCode -ne 0) {
                $tail = if (Test-Path $pipLog) { Get-Content $pipLog -Tail 20 | Out-String } else { "" }
                throw "pip install failed with exit code $($pipProc.ExitCode)`n$tail"
            }
            Remove-Item -LiteralPath $pipLog -Force -ErrorAction SilentlyContinue
        }

        [void](New-Item -ItemType File -Force -Path $PipSentinel)
        Finish-Ok "pip_install" "packages installed"
        $okCount++
    }
} catch {
    $failCount++
    $msg = $_.Exception.Message -replace "\|", ":"
    Emit "ERROR" "configure|1|$msg"
    Write-Color "Error: $msg" Red
}

Emit "COMPLETE" "${okCount}|${skipCount}|${failCount}"

if (-not $Electron) {
    Write-Host ""
    if ($failCount -gt 0) {
        Write-Host "Finished with failures: $okCount ok, $skipCount skipped, $failCount failed" -ForegroundColor Yellow
    } else {
        Write-Host "All done: $okCount ok, $skipCount skipped" -ForegroundColor Green
    }
}

if ($failCount -gt 0) { exit 1 } else { exit 0 }
