# Installation
Open Sublime Text. At the top navigation bar, locate **Preferences** and select **Browse Packages**.

Create a new folder called **IDEKA**. Copy all files from `IDEKALang/editor-support/sublime/` into the new **IDEKA** folder you just created in your Sublime Packages parent folder.

## Usage
Open any IDEKA source file (`.idk` extension) and Sublime should do the rest!

----

## Configuring builds with `IDEKA.sublime-build`
You will need to modify this file to make use of Sublime's built-in `CTRL+B` to compile feature.  
Here's how to set it up:
```
{
    "shell_cmd": "python \"__YOUR_PATH_TO_IDEKA_HERE__\" \"$file\"",
    "working_dir": "__YOUR_PATH_TO_IDEKA_HERE__",
    "selector": "source.idk",
    
    "target": "exec",
    "quiet": false,
    
    // Force UTF-8 encoding
    "encoding": "utf-8",
    "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
    },
    
    "windows": {
        "shell_cmd": "chcp 65001 >nul && python \"__YOUR_PATH_TO_IDEKA_HERE__\" \"$file\" 2>&1"
    }
}
```

Simply replace all occurances of `__YOUR_PATH_TO_IDEKA_HERE__`.
