; Custom NSIS uninstaller — cleanup runtime-downloaded files not tracked by the installer
!macro customUnInstall
  ; ComfyUI engine (downloaded on first run, ~30 GB expanded)
  RMDir /r "$INSTDIR\resources\backend\ComfyUI_windows_portable_nvidia"
  ; Temporary download artifacts
  Delete "$INSTDIR\resources\backend\_7za.exe"
  Delete "$INSTDIR\resources\backend\_gguf_extract_temp"
!macroend
