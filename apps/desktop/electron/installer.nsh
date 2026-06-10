; Custom NSIS uninstaller — cleanup runtime-downloaded files not tracked by the installer
!macro customUnInstall
  ${ifNot} ${isUpdated}
    ; Clean uninstall: remove ComfyUI engine and models (~30 GB expanded)
    RMDir /r "$INSTDIR\resources\backend\ComfyUI_windows_portable_nvidia"
  ${else}
    ; Update: preserve ComfyUI engine and models so the new version doesn't
    ; need to re-download ~30 GB. Move to a sibling directory outside $INSTDIR
    ; so it survives the RMDir /r $INSTDIR that follows this macro.
    IfFileExists "$INSTDIR\resources\backend\ComfyUI_windows_portable_nvidia" 0 +3
      RMDir /r "$INSTDIR\..\Gen2Vec_ComfyUI_Backup"
      CreateDirectory "$INSTDIR\..\Gen2Vec_ComfyUI_Backup"
      Rename "$INSTDIR\resources\backend\ComfyUI_windows_portable_nvidia" "$INSTDIR\..\Gen2Vec_ComfyUI_Backup\ComfyUI_windows_portable_nvidia"
  ${endif}
  ; Always clean temporary extraction artifacts (small, safe to delete)
  Delete "$INSTDIR\resources\backend\_gguf_extract_temp"
!macroend

; Restore ComfyUI engine and models after an update completes.
; NOTE: Do NOT guard with ${isUpdated} — the installer itself does NOT receive
; --updated on its command line (only the OLD uninstaller does). Instead, simply
; check if the backup directory exists and restore it if so.
!macro customInstall
  IfFileExists "$INSTDIR\..\Gen2Vec_ComfyUI_Backup\ComfyUI_windows_portable_nvidia" 0 +3
    CreateDirectory "$INSTDIR\resources\backend"
    Rename "$INSTDIR\..\Gen2Vec_ComfyUI_Backup\ComfyUI_windows_portable_nvidia" "$INSTDIR\resources\backend\ComfyUI_windows_portable_nvidia"
    ; Clean up the (now empty) backup directory
    RMDir "$INSTDIR\..\Gen2Vec_ComfyUI_Backup"
!macroend
