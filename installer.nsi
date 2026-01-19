; Archivarr Installer Script for NSIS
; This creates a professional Windows installer for Archivarr

!include "MUI2.nsh"
!include "x64.nsh"

; Installer settings
Name "Archivarr"
OutFile "Archivarr-Installer.exe"
InstallDir "$PROGRAMFILES\Archivarr"
InstallDirRegKey HKCU "Software\Archivarr" ""

; MUI Settings
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

; Installer sections
Section "Install"
    SetOutPath "$INSTDIR"
    
    ; Copy executable and all files from dist folder
    File /r "dist\Archivarr\*.*"
    
    ; Create Start Menu shortcuts
    CreateDirectory "$SMPROGRAMS\Archivarr"
    CreateShortcut "$SMPROGRAMS\Archivarr\Archivarr.lnk" "$INSTDIR\Archivarr.exe"
    CreateShortcut "$SMPROGRAMS\Archivarr\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
    
    ; Create Desktop shortcut
    CreateShortcut "$DESKTOP\Archivarr.lnk" "$INSTDIR\Archivarr.exe"
    
    ; Create uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    
    ; Registry entries for uninstall
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Archivarr" "DisplayName" "Archivarr"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Archivarr" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Archivarr" "DisplayIcon" "$INSTDIR\Archivarr.exe"
SectionEnd

; Uninstaller section
Section "Uninstall"
    ; Remove executable and files
    RMDir /r "$INSTDIR"
    
    ; Remove Start Menu shortcuts
    RMDir /r "$SMPROGRAMS\Archivarr"
    
    ; Remove Desktop shortcut
    Delete "$DESKTOP\Archivarr.lnk"
    
    ; Remove registry entries
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Archivarr"
    DeleteRegKey HKCU "Software\Archivarr"
SectionEnd
