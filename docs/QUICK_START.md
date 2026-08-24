# GiloDAM V1 Alpha — Quick Start

This build is the first working vertical slice of GiloDAM. It catalogs media in place. It does not move, rename, overwrite, or delete original files.

## Run the source build on Windows

1. Unzip the GiloDAM project folder.
2. If compatible Python is already installed, double-click `START_GILODAM_WINDOWS.bat`.
3. If Windows reports that compatible Python was not found, double-click `INSTALL_PYTHON_AND_START.bat`, review the prompt, and answer `Y`. This uses Windows Package Manager to install 64-bit Python 3.12 for the current user, then continues setup.
4. The first launch creates a private environment and installs the two preview dependencies. Later launches are faster.
5. In GiloDAM, choose **Add Folder** and select a test folder first.
6. Review the read-only analysis, then choose **Index All** or **Review Selection**.

GiloDAM accepts either the Python launcher (`py.exe`) or a standard `python.exe` installation. Python must be 64-bit and version 3.11 or newer. The assisted install requires an explicit `Y` response and does not require an administrator account.

The local catalog is stored under `%LOCALAPPDATA%\GiloDAM`. Closing the application does not remove it. Opening GiloDAM again restores the same asset IDs and metadata.

## First safe test

Use a copy of a small mixed-media folder containing a few JPG or PNG images, a TXT or Markdown file, and—if useful—two identical copies of one image. Confirm that the Review screen shows the file-type totals and duplicate count before indexing.

After indexing:

1. Select an image and confirm that its preview and technical metadata appear.
2. Enter a Title.
3. Choose a vocabulary, add a suggested or freeform keyword, and choose **Save to Catalog**.
4. Search for the Title or keyword.
5. Choose **Sync JSON Sidecar** only if you want a portable `.gilodam.json` file written beside that original.
6. Close and reopen GiloDAM; confirm the catalog returns.

## Build the Windows application

If compatible Python is already installed, double-click `BUILD_WINDOWS.bat`. Otherwise, double-click `INSTALL_PYTHON_AND_BUILD.bat`, review the prompt, and answer `Y`. The assisted path installs Python for the current Windows user and then runs the same build gates:

1. Creates an isolated build environment.
2. Installs the runtime and packaging dependencies.
3. Runs the complete automated test suite.
4. Builds `GiloDAM.exe` as a portable folder.
5. Runs the packaged executable's self-test.
6. Creates a portable ZIP and SHA-256 checksum in `release`.
7. If Inno Setup 6 is installed, also creates a per-user, non-admin Windows installer with Start Menu and optional desktop shortcuts.

An unsigned private installer may trigger Windows SmartScreen. Code signing is a productization step, not a functional requirement of this alpha.

## Python-launcher troubleshooting

If an older Alpha 1 folder reports `Python's Windows launcher (py.exe) was not found`, that message comes from the old build script. It does not mean the catalog or media were damaged. Use the Alpha 2 source package and run `INSTALL_PYTHON_AND_BUILD.bat`; the revised script detects both `py.exe` and normal `python.exe` installations.

If Windows Package Manager is unavailable, the assisted batch opens the official Python Windows download page. Install 64-bit Python 3.11 or newer for your user account, then run `BUILD_WINDOWS.bat` or `START_GILODAM_WINDOWS.bat` again.

## If GiloDAM does not start

Open Command Prompt in the project folder and run:

```bat
.venv\Scripts\python.exe run_gilodam.py --self-test
```

The diagnostic confirms catalog startup and SQLite integrity without opening the interface or scanning any media. Logs are under `%LOCALAPPDATA%\GiloDAM\logs`.

## Close and restart behavior

GiloDAM has no background watch process in this alpha. Choosing Exit or closing the window cancels active work at a safe file boundary, stops the slideshow, records the window size, closes the interface, and leaves no installer-dependent restart state. You should not need to reinstall to reopen it.
