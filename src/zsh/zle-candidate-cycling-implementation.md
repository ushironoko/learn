# ZLE Widget による候補サイクリング実装の知見

## 概要

zsh の ZLE (Zsh Line Editor) widget で Tab サイクリング UI を実装する際に得た知見をまとめる。`zle -M` の制約、coproc ライフサイクル管理、hook chaining、Rust バイナリパス埋め込みパターンを含む。

## 背景・きっかけ

zsh abbreviation expansion ツール kort の prefix candidate 機能で、入力途中の候補を Tab/Shift+Tab でサイクリングする UX を実装した。

## 学んだこと

### zle -M は ANSI エスケープを一切解釈しない

`zle -M` はステータスバー領域にメッセージを表示する ZLE 組み込みだが、ANSI エスケープシーケンスをそのまま文字列として表示する。

試した手法と結果:
- `\x1b[7m` (reverse video) → `^[[7m` と表示
- `\e[7m` → 同上
- `%S` / `%s` (zsh prompt escape) → `^[[7m` / `^[[27m` と表示
- `${(%)text}` パラメータフラグ → 同上

**結論**: `zle -M` でハイライト表現は不可能。テキストマーカー (`▸`) で選択状態を表現するのが唯一の実用的手段。

```zsh
# NG: ANSI エスケープは caret notation になる
zle -M $'\x1b[7m selected \x1b[0m'  # → ^[[7m selected ^[[0m

# OK: テキストマーカーで代替
if (( i == _KORT_CYCLE_INDEX )); then
  msg+="▸ ${ckw} → ${cexp}"
else
  msg+="  ${ckw} → ${cexp}"
fi
zle -M "$msg"
```

### coproc のライフサイクル管理

zsh の coproc はジョブテーブルとは別に管理され、通常のジョブ制御コマンドが効かない。

**問題1: `disown` が使えない**
coproc に対して `disown` は無効。バックグラウンドジョブとは管理体系が異なる。

**問題2: `CHECK_JOBS` が exit をブロック**
coproc が動作中だと `exit` 時に "you have running jobs" 警告が出る。

**解決策**: exit/logout 実行前に明示的に coproc を kill する。

```zsh
# kort-expand-accept widget 内
if [[ "$BUFFER" == exit || "$BUFFER" == logout ]]; then
  _kort_stop_coproc
fi
```

**問題3: ジョブ通知 `[3] 47269` がシェルリロード時に表示される**

**解決策**: `setopt local_options no_monitor no_notify` を coproc 起動/停止関数で使用。`local_options` により関数スコープ限定で自動復元される。

```zsh
_kort_start_coproc() {
  setopt local_options no_monitor no_notify
  _kort_stop_coproc
  coproc $_KORT_BIN serve 2>/dev/null
  _KORT_COPROC_PID=$!
}
```

### add-zle-hook-widget による hook chaining

`zle -N zle-line-pre-redraw func` は既存のフックを上書きしてしまう。`add-zle-hook-widget` を使えば複数のフックを共存させられる。

```zsh
# autoload して使う (zsh ≥5.3)
autoload -Uz +X add-zle-hook-widget 2>/dev/null
if (( $+functions[add-zle-hook-widget] )); then
  add-zle-hook-widget line-pre-redraw _kort_check_cycling
else
  # フォールバック: 古い zsh 向け
  zle -N zle-line-pre-redraw _kort_check_cycling
fi
```

### LASTWIDGET ベースのサイクリングキャンセル

`line-pre-redraw` フック内で `$LASTWIDGET` を参照し、kort 以外の widget が呼ばれたらサイクリングを解除する。

```zsh
_kort_check_cycling() {
  if (( _KORT_CYCLING )); then
    case "$LASTWIDGET" in
      kort-expand-space|kort-expand-accept|kort-next-placeholder|\
      kort-prev-candidate|kort-literal-space) ;;
      *) _kort_clear_candidates 0 ;;
    esac
  fi
}
```

`restore` パラメータ: `0` = 現在の候補を維持（ユーザーの次のキー入力を尊重）、`1` = 元のトークンを復元。

### std::env::current_exe() によるバイナリ絶対パス埋め込み

coproc で `kort serve` を呼ぶ際、`kort` が PATH にないと `exit 127` になる。テンプレート置換パターンで解決。

```rust
// src/main.rs
fn cmd_init_zsh() -> Result<()> {
    let kort_bin = std::env::current_exe()
        .context("failed to determine kort binary path")?
        .to_string_lossy()
        .to_string();
    let script = include_str!("../shells/zsh/kort.zsh");
    print!("{}", script.replace("__KORT_BIN__", &kort_bin));
    Ok(())
}
```

```zsh
# shells/zsh/kort.zsh (テンプレート)
typeset -g _KORT_BIN="__KORT_BIN__"
# → eval 後: _KORT_BIN="/Users/user/.cargo/bin/kort"

# 全コマンド呼び出しで $_KORT_BIN を使用
coproc $_KORT_BIN serve 2>/dev/null
```

## ポイント

- `zle -M` はプレーンテキスト専用。ハイライトが必要ならテキストマーカーで代替する
- coproc は `disown` 不可。exit 前に明示的 kill + `no_monitor no_notify` でジョブ通知抑制
- `add-zle-hook-widget` で hook chaining。`zle -N zle-*` は既存フックを破壊する
- `$LASTWIDGET` で直前の widget を判定し、状態機械の遷移を制御できる
- `std::env::current_exe()` + テンプレート置換で PATH 非依存のバイナリ参照を実現

## 参考

- [zshzle(1) - zle -M](https://zsh.sourceforge.io/Doc/Release/Zsh-Line-Editor.html)
- [add-zle-hook-widget](https://zsh.sourceforge.io/Doc/Release/User-Contributions.html#Widgets)
