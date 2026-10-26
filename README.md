# GripPreview for Sublime Text 4

Preview Markdown files in the browser, rendered GitHub-style by [go-grip](https://github.com/chrishrb/go-grip), or serve a whole project folder. The preview reloads on every save.


## Install

Requires Sublime Text 4, build 4213 or later, and the go-grip program (see [## go-grip](#go-grip)).

Download the latest [Release](https://github.com/Gregory-K/GripPreview/releases) and extract it into the `Packages` folder, no renaming needed.

Or clone this repository into your `Packages` folder:

Linux:  
```sh
git clone -b master https://github.com/Gregory-K/GripPreview.git ~/.config/sublime-text/Packages/GripPreview
```

Windows:  
```pwsh
git clone -b master https://github.com/Gregory-K/GripPreview.git "$env:APPDATA\Sublime Text\Packages\GripPreview"

# or CMD
git clone -b master https://github.com/Gregory-K/GripPreview.git "%APPDATA%\Sublime Text\Packages\GripPreview"
```

macOS:  
```sh
git clone -b master https://github.com/Gregory-K/GripPreview.git ~/Library/Application\ Support/Sublime\ Text/Packages/GripPreview
```


## go-grip

The package runs [go-grip](https://github.com/chrishrb/go-grip) but does not include it. It looks for go-grip in this order and uses the first one it finds:

1. the `go_grip_binary` setting, when set
2. `go-grip` in `PATH`
3. the copy the package downloaded,  
  in Sublime Text's `Package Storage/GripPreview/go-grip/<version>/` folder

When you 'preview' or 'serve' and it finds none, it offers to download go-grip, or to open the settings so you can point `go_grip_binary` to one you have. It downloads the go-grip from the [go-grip releases](https://github.com/chrishrb/go-grip/releases) on GitHub. The download is checked against the release's MD5 checksum and kept with its licence. Nothing is downloaded without asking.

To install go-grip yourself instead,  
- download it from the go-grip releases and put it in `PATH`, or
- run `go install github.com/chrishrb/go-grip@latest`


## Preview a file

`GripPreview: Preview File`, in the command palette, opens the current file in the default browser. It is available for saved Markdown files, and for other filetypes you add in the settings. The preview reloads on every save.

go-grip renders `.md` files only. It serves other files with their MIME type, and the browser displays them accordingly, e.g. a `.markdown` or `.txt` file as plain text, and an image or a PDF in its own viewer.

go-grip serves the folder around the file, not the file alone. A file inside the project is served from its project folder, so links to other files of the project work. A file outside the project is served from its own folder. Links cannot reach above the served folder.

Each served folder gets its own go-grip server. Previewing another file under a served folder reuses its server and only opens a new browser tab.


## Serve a project folder

`GripPreview: Serve Project Folder` serves a folder of the window's project and opens its `README.md`, or a list of its files when there is none. With several project folders, a list asks which one. Every `.md` file under the folder then opens rendered.


## Stop servers

`GripPreview: Stop Server` lists the running servers, with their ports, to stop one or all of them. All servers stop when Sublime Text exits, and when the package is reloaded or upgraded.

Stop Server knows only the servers of the current Sublime Text session. Servers left over from a session that crashed keep running, unknown to it.  
`GripPreview: Stop Server (Force All)` ends them. It ends every go-grip process on the computer, including ones you started outside Sublime Text.


## Settings

`Preferences > Package Settings > GripPreview > Settings`,  
or `Preferences: GripPreview: Settings` in the command palette.

- `go_grip_binary`: the go-grip program to run. A path, where `~` and environment variables work, e.g. `~/go/bin/go-grip`, or a name to look up in `PATH`. Empty to look it up as described in [## go-grip](#go-grip).
- `preview_selector`: the files Preview File is available for, as a scope selector. The default, `text.html.markdown`, matches files with a Markdown syntax. Add others with a comma, e.g. `text.html.markdown, text.plain`.
- `preview_extensions`: more files Preview File is available for, by extension, with or without the dot, e.g. `[".txt", "rst"]`.
- `port`: the port of the go-grip servers. `0` gives each served folder a free port. Any other port gives a fixed address, but only one folder can be served at a time.


## Key bindings

There are none by default.  
`Preferences > Package Settings > GripPreview > Key Bindings – User` opens your own key bindings, where you can add the ones you want.  

Here are examples for every command, as chords on `alt+m`,  
e.g. `alt+m` then `p` to preview:

```json
[
  // Preview File
  { "keys": ["alt+m", "p"], "command": "grip_preview" },
  // Serve Project Folder
  { "keys": ["alt+m", "f"], "command": "grip_preview_serve_folder" },
  // Stop Server
  { "keys": ["alt+m", "s"], "command": "grip_preview_stop" },
  // Stop Server (Force All), asks first
  { "keys": ["alt+m", "k"], "command": "grip_preview_stop_force_all" },
  // Settings
  {
    "keys": ["alt+m", ","],
    "command": "edit_settings",
    "args": {
      "base_file": "${packages}/GripPreview/GripPreview.sublime-settings",
      "default": "{\n\t$0\n}\n"
    }
  }
]
```


## Network access

go-grip listens on all network interfaces, not only on `localhost`, even though the preview opens at a `localhost` address. Anyone on your network who can reach your computer on a served port can read every file under the served folder, not only its Markdown files. Windows Firewall may ask about this the first time go-grip runs. Deny access there to keep the servers local.


## License

MIT License, see [License.txt](License.txt).
