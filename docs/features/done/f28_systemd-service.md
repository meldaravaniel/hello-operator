### F-28 · systemd service file template

**Background**
Without a service file the application must be started manually in a terminal on every boot, does not restart on crash, and does not integrate with the system log. A systemd unit template checked into the repo gives deployers everything they need; path substitution is performed at deploy time (by the install script, f30) so no absolute paths are hardcoded in the repo.

**Changes required**

#### 1. `hello-operator.service.template` — add to project root

```ini
[Unit]
Description=Hello Operator — rotary phone Plex controller
After=network.target sound.target

[Service]
Type=simple
User=%%USER%%
WorkingDirectory=%%INSTALL_DIR%%
EnvironmentFile=/etc/hello-operator/config.env
ExecStart=%%INSTALL_DIR%%/venv/bin/python main.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=hello-operator

[Install]
WantedBy=multi-user.target
```

The placeholders `%%INSTALL_DIR%%` and `%%USER%%` are substituted at deploy time with the absolute path of the project directory and the name of the non-root deploying user respectively.

#### 2. `.gitignore` — add `hello-operator.service`

The generated (substituted) unit file should never be committed. Add it to `.gitignore` so it is not accidentally staged.

**Design notes:**
- `EnvironmentFile=/etc/hello-operator/config.env` — loads all variables defined in f28's config file before starting the process.
- `After=sound.target` — ensures the audio subsystem is ready before hello-operator opens a sounddevice stream.
- `Restart=on-failure` with `RestartSec=5` — recovers from crashes without flooding the log on rapid repeated failures.
- `SyslogIdentifier=hello-operator` — makes `journalctl -u hello-operator` the canonical log command.
- The default `User` is the non-root user who ran the install. On standard Raspberry Pi OS the default user is already a member of the `gpio`, `audio`, and `plugdev` groups, so no additional group setup is required.

**Acceptance criteria**
- `hello-operator.service.template` is present at the project root containing both `%%INSTALL_DIR%%` and `%%USER%%` placeholders.
- `hello-operator.service` (without `.template`) is listed in `.gitignore`.
- After substituting both placeholders with arbitrary values, the resulting text is a well-formed systemd unit file (contains `[Unit]`, `[Service]`, and `[Install]` sections; no remaining `%%` placeholders).

**Testable outcome**
New test in `tests/test_service_template.py`:

- `test_template_exists` — assert `hello-operator.service.template` exists at the project root.
- `test_template_contains_placeholders` — read the template; assert both `%%INSTALL_DIR%%` and `%%USER%%` appear in its contents.
- `test_substitution_removes_all_placeholders` — perform `str.replace("%%INSTALL_DIR%%", "/some/path")` and `str.replace("%%USER%%", "alice")` on the template content; assert no `%%` substrings remain in the result.
- `test_substituted_output_has_required_sections` — after substitution, assert the text contains `[Unit]`, `[Service]`, and `[Install]`.
- `test_substituted_exec_start_contains_path` — after substitution with `INSTALL_DIR="/some/path"`, assert `ExecStart` line contains `/some/path`.
- `test_generated_file_not_tracked` — read `.gitignore` and assert `hello-operator.service` appears in it.
