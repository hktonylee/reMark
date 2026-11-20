# Example plugins

Drop any `*.py` in this directory into your
`plugins.plugin_dir` (default `~/.config/remark/plugins`) to enable it.
None of these ship in the default distribution — they live here as
reference implementations.

## math_latex_plugin.py

Auto-wraps bare LaTeX fragments in `$...$` (or `$$...$$` for
`\begin{equation}` blocks) so Obsidian renders them as math. Pure text
pass, no image access needed.

**Install:**
```bash
cp math_latex_plugin.py ~/.config/remark/plugins/
```

**Settings (optional, in `config.yaml`):**
```yaml
plugins:
  enabled: true
  settings:
    math_latex:
      wrap_inline: true
      wrap_block: true
```
