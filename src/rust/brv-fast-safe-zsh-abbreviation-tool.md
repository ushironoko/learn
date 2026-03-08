# brv: Rust製の高速・安全な zsh abbreviation 展開ツールの設計と実装

## 概要

zsh の abbreviation 展開ツール brv (brevis = ラテン語で「短い」) を Rust で設計・実装した。`brv compile` による事前検証 + bincode バイナリキャッシュで、パフォーマンスと安全性の両方を実現する。このドキュメントでは、設計判断、実装パターン、得られた知見を詳細に記録する。

## 背景・きっかけ

既存の zsh abbreviation ツールには2つの深刻な問題がある:

1. **パフォーマンス**: zeno.zsh は Deno ランタイムに依存しコールドスタート ~150ms。zsh-abbr は純粋 zsh 実装だが 100件超の abbreviation で初期化が O(n) で劣化
2. **安全性**: abbreviation キーワードが既存コマンドと衝突するリスク。実例として `alias cc='claude ...'` が tree-sitter の C コンパイルで `cc` (Unix C コンパイラ) を乗っ取り、Claude Code が大量起動 → メモリ 40GB 消費でシステムハング

## 学んだこと

### 1. 事前コンパイル + バイナリキャッシュアーキテクチャ

#### 設計思想: 「重い処理は1回だけ、毎回の展開は最速に」

TOML 設定ファイルを毎回パースするのではなく、`brv compile` で事前にバイナリキャッシュ (bincode) を生成する。キー入力のたびに呼ばれる `brv expand` ではキャッシュの読み込みと HashMap ルックアップのみ行う。

```
brv.toml (TOML設定)
    │
    ▼
brv compile ─── PATH スキャン + ビルトイン照合 ─── 衝突検出
    │
    ▼
brv.cache (バイナリキャッシュ: bincode)
    │
    ▼
brv expand ─── キャッシュ読み込み → HashMap ルックアップ → stdout 出力
```

#### bincode によるシリアライズ

bincode は Rust のバイナリシリアライザで、JSON や TOML に比べて:
- **高速**: デシリアライズが数倍速い (パースレスに近い)
- **コンパクト**: バイナリ表現なのでファイルサイズが小さい
- **型安全**: serde の Serialize/Deserialize を derive するだけで使える

```rust
#[derive(Debug, Serialize, Deserialize)]
pub struct CompiledCache {
    pub version: u32,
    pub config_hash: u64,  // 鮮度チェック用
    pub matcher: Matcher,
}

// 書き込み
let encoded = bincode::serialize(&cache)?;
std::fs::write(output_path, encoded)?;

// 読み込み
let data = std::fs::read(cache_path)?;
let cache: CompiledCache = bincode::deserialize(&data)?;
```

#### config_hash による鮮度チェック

設定ファイルの内容を DefaultHasher でハッシュ化し、キャッシュに埋め込む。`brv expand` 実行時にキャッシュのハッシュと現在の設定ファイルのハッシュを比較し、不一致なら `stale_cache` を返す。ZLE ウィジェット側が自動で `brv compile` を再実行する。

```rust
pub fn hash_config(content: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    content.hash(&mut hasher);
    hasher.finish()
}

pub fn is_fresh(cache: &CompiledCache, config_path: &Path) -> Result<bool> {
    let config_content = std::fs::read_to_string(config_path)?;
    let current_hash = hash_config(&config_content);
    Ok(cache.config_hash == current_hash)
}
```

**学び**: 設定ファイルの変更検出は、mtime (修正時刻) より内容ハッシュの方が信頼性が高い。mtime はファイルコピーやエディタの保存方式によって不正確になることがある。

---

### 2. FxHashMap による O(1) ルックアップ

#### rustc-hash の FxHashMap

標準ライブラリの HashMap は SipHash を使っており、HashDoS 耐性がある代わりにやや遅い。abbreviation のキーワードルックアップでは外部入力の攻撃を考慮する必要がないため、Firefox 由来の FxHash を使う。

```rust
use rustc_hash::FxHashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Matcher {
    /// コマンド位置専用 (keyword → compiled abbreviations)
    pub regular: FxHashMap<String, Vec<CompiledAbbr>>,
    /// グローバル (keyword → compiled abbreviations)
    pub global: FxHashMap<String, Vec<CompiledAbbr>>,
    /// コンテキスト付き (正規表現マッチが必要)
    pub contextual: Vec<CompiledAbbr>,
}
```

#### 3階層ルックアップ戦略

展開時のルックアップは3段階の優先順位で行う:

1. **コンテキスト付き (contextual)**: 正規表現マッチが必要 → Vec を線形走査
2. **コマンド位置 (regular)**: lbuffer にスペースが含まれない場合のみ → FxHashMap O(1)
3. **グローバル (global)**: 位置を問わず → FxHashMap O(1)

```rust
pub fn expand(input: &ExpandInput, matcher_data: &Matcher) -> ExpandOutput {
    let Some((prefix, keyword)) = extract_keyword(&input.lbuffer) else {
        return ExpandOutput::NoMatch;
    };

    // 1. コンテキスト付きを最優先
    if let Some(abbr) = context::find_contextual_match(
        &matcher_data.contextual, keyword, prefix, &input.rbuffer
    ) {
        return build_output(prefix, abbr, &input.rbuffer);
    }

    // 2. コマンド位置なら regular を検索
    if is_command_position(prefix) {
        if let Some(abbr) = matcher::lookup_regular(matcher_data, keyword) {
            return build_output(prefix, abbr, &input.rbuffer);
        }
    }

    // 3. グローバルを検索
    if let Some(abbr) = matcher::lookup_global(matcher_data, keyword) {
        return build_output(prefix, abbr, &input.rbuffer);
    }

    ExpandOutput::NoMatch
}
```

**学び**: contextual abbreviation は正規表現マッチが必要なため HashMap に入れられない。ただし通常の使用では contextual の数は少ない (10件以下) ため、線形走査でも十分高速。データの性質に合わせてデータ構造を使い分けるのが重要。

---

### 3. 衝突検出エンジン (conflict.rs)

#### 検出パターン

abbreviation キーワードが既存コマンドやシェルビルトインと衝突するリスクを事前に検出する。

| パターン | 例 | 重大度 |
|---------|-----|--------|
| PATH 完全一致 | `cc` → `/usr/bin/cc` | エラー (コンパイル失敗) |
| PATH サフィックス一致 | `cc` → `gcc` の末尾 | 警告 (--strict でエラー化) |
| シェルビルトイン | `cd`, `echo`, `test` | エラー (コンパイル失敗) |

#### PATH スキャン実装

`$PATH` 環境変数を `:` で分割し、各ディレクトリの実行可能ファイルを収集する。重複回避のために `FxHashSet` で管理。

```rust
pub fn scan_path() -> Vec<(String, PathBuf)> {
    let path_var = match std::env::var("PATH") {
        Ok(p) => p,
        Err(_) => return Vec::new(),
    };

    let mut commands = Vec::new();
    let mut seen = rustc_hash::FxHashSet::default();

    for dir in path_var.split(':') {
        let dir_path = PathBuf::from(dir);
        let entries = match std::fs::read_dir(&dir_path) {
            Ok(e) => e,
            Err(_) => continue,  // 存在しないディレクトリはスキップ
        };

        for entry in entries.flatten() {
            let file_name = entry.file_name().to_string_lossy().to_string();

            if seen.contains(&file_name) {
                continue;  // 最初に見つかったものを優先 (PATH の順序を尊重)
            }

            // Unix: 実行権限ビットをチェック
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                if let Ok(metadata) = entry.metadata() {
                    if metadata.is_file() && metadata.permissions().mode() & 0o111 != 0 {
                        seen.insert(file_name.clone());
                        commands.push((file_name, entry.path()));
                    }
                }
            }
        }
    }

    commands
}
```

**学び**:
- `#[cfg(unix)]` で Unix 固有のパーミッションチェックを分離する
- `entries.flatten()` で `Result` のエラーを暗黙にスキップ (`read_dir` の各エントリは `Result<DirEntry>`)
- PATH の順序を尊重し、最初に見つかったコマンドを優先するのが重要 (シェルの実際の挙動と一致)

#### zsh ビルトインのハードコード

シェルビルトインは動的に変わらないため、ハードコードする。`enable`/`disable` で動的に変更されるケースは稀で、安全側に倒す設計。

```rust
pub fn zsh_builtins() -> &'static [&'static str] {
    &[
        "alias", "autoload", "bg", "bindkey", "break", "builtin",
        "cd", "command", "echo", "eval", "exec", "exit", "export",
        "false", "kill", "local", "print", "printf", "pwd", "read",
        "return", "set", "shift", "source", "test", "true", "type",
        "which", "zle", "zmodload", "zparseopts",
        // ... 90+ エントリ
    ]
}
```

#### allow_conflict による個別許可

衝突を認識した上で意図的に使いたいケースがある (例: `gs` を `git status` に割り当てたいが、`gs` = Ghostscript が PATH にある)。`allow_conflict = true` で個別に許可できる。

```toml
[[abbr]]
keyword = "gs"
expansion = "git status --short"
allow_conflict = true  # /usr/local/bin/gs (Ghostscript) との衝突を許可
```

```rust
for abbr in abbreviations {
    if abbr.allow_conflict {
        continue;  // 衝突チェックをスキップ
    }
    // ... 衝突検出ロジック
}
```

**学び**: 安全機構は「デフォルトで厳格、明示的に緩和」が正しいパターン。ユーザーが意図的に危険な操作をする場合は、その意思を明示的に記録させる。

---

### 4. ZLE ウィジェット統合プロトコル

#### stdout ベースのプロトコル設計

brv と zsh の通信は stdout の行ベースプロトコルで行う。brv はシェルの状態を一切変更せず、ZLE ウィジェットが stdout を読んで `$BUFFER` と `$CURSOR` を書き換える。

```
# 展開成功時 (3行)
success
<new_buffer>
<new_cursor_position>

# マッチなし
no_match

# コマンド評価が必要 (4行)
evaluate
<command>
<prefix>
<rbuffer>

# キャッシュが古い
stale_cache
```

#### ZLE ウィジェット実装

```zsh
brv-expand-space() {
  local -a out
  out=( "${(f)$(brv expand --lbuffer="$LBUFFER" --rbuffer="$RBUFFER")}" )

  case $out[1] in
    success)
      if [[ -n $out[2] ]]; then
        BUFFER=$out[2]
        CURSOR=$out[3]
      else
        zle self-insert
      fi
      ;;
    evaluate)
      local result
      result=$(eval "$out[2]" 2>/dev/null)
      if [[ -n $result ]]; then
        BUFFER="${out[3]}${result}${out[4]}"
        CURSOR=$(( ${#out[3]} + ${#result} ))
      fi
      ;;
    stale_cache)
      brv compile 2>/dev/null  # 自動再コンパイル
      # リトライ
      out=( "${(f)$(brv expand --lbuffer="$LBUFFER" --rbuffer="$RBUFFER")}" )
      if [[ $out[1] == "success" && -n $out[2] ]]; then
        BUFFER=$out[2]
        CURSOR=$out[3]
      else
        zle self-insert
      fi
      ;;
    *)
      zle self-insert  # マッチなし → 通常のスペース挿入
      ;;
  esac
}

zle -N brv-expand-space
bindkey " " brv-expand-space
```

**学び**:
- `"${(f)$(...)}"` は zsh の parameter expansion flag で、コマンド出力を改行で分割して配列にする
- `$LBUFFER` と `$RBUFFER` は ZLE が提供する変数で、カーソルの左右のテキストを表す
- `zle self-insert` はデフォルトのキー動作 (スペースならスペース挿入) にフォールバック
- `stale_cache` パターンにより、設定変更後に手動で `brv compile` を再実行する必要がない

#### lbuffer/rbuffer の分離

zsh の ZLE は `$BUFFER` (全体) と `$CURSOR` (カーソル位置) の代わりに、`$LBUFFER` (カーソル左) と `$RBUFFER` (カーソル右) も提供する。brv はこの分離をそのまま引数として受け取る:

```
$ echo hello|world
       ^     ^
       LBUFFER="echo hello"
              RBUFFER="world"
```

これにより、キーワードの抽出 (lbuffer の末尾トークン) とコンテキスト判定 (lbuffer の正規表現マッチ) が自然に実装できる。

---

### 5. プレースホルダーシステム

#### `{{placeholder}}` の処理

abbreviation の展開テキストに `{{placeholder}}` を含めることで、展開後にカーソルをその位置に移動できる。

```toml
[[abbr]]
keyword = "gc"
expansion = "git commit -m '{{message}}'"
```

展開時に最初のプレースホルダーを除去し、その開始位置をカーソル位置として返す:

```rust
pub fn apply_first_placeholder(text: &str, default_cursor: usize) -> PlaceholderResult {
    if let Some(start) = text.find("{{") {
        if let Some(end) = text[start..].find("}}") {
            let end_pos = start + end + 2;
            let mut result = String::with_capacity(text.len() - (end_pos - start));
            result.push_str(&text[..start]);
            result.push_str(&text[end_pos..]);
            return PlaceholderResult {
                text: result,
                cursor: start,
            };
        }
    }
    PlaceholderResult {
        text: text.to_string(),
        cursor: default_cursor,
    }
}
```

`gc` → `git commit -m '|'` (カーソルがシングルクォート内に移動)

#### Tab キーによるプレースホルダージャンプ

複数のプレースホルダーがある場合、Tab キーで次のプレースホルダーにジャンプできる。カーソル位置以降を先に検索し、見つからなければ先頭からラップアラウンドする。

---

### 6. clap derive による CLI 設計

#### サブコマンドパターン

```rust
#[derive(Parser, Debug)]
#[command(name = "brv")]
#[command(about = "Fast and safe abbreviation expansion for zsh")]
#[command(version)]
struct Args {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Compile config and verify conflicts
    Compile {
        #[arg(long, default_value = "false")]
        strict: bool,
        #[arg(long)]
        config: Option<PathBuf>,
    },
    /// Expand abbreviation (called from ZLE)
    Expand {
        #[arg(long)]
        lbuffer: String,
        #[arg(long)]
        rbuffer: String,
        #[arg(long)]
        cache: Option<PathBuf>,
        #[arg(long)]
        config: Option<PathBuf>,
    },
    // ...
}
```

**学び**: `///` doc comment がそのまま `--help` のテキストになる。ユーザー向けメッセージはすべて英語にすべき (国際的な CLI ツールとして)。

#### XDG Base Directory 対応

`xdg` クレートでプラットフォームに応じた設定・キャッシュディレクトリを取得する:

```rust
pub fn default_config_path() -> Result<PathBuf> {
    let xdg = xdg::BaseDirectories::with_prefix("brv")?;
    Ok(xdg.get_config_home().join("brv.toml"))  // ~/.config/brv/brv.toml
}

pub fn default_cache_path() -> Result<PathBuf> {
    let xdg = xdg::BaseDirectories::with_prefix("brv")?;
    Ok(xdg.get_cache_home().join("brv.cache"))  // ~/.cache/brv/brv.cache
}
```

---

### 7. テスト戦略

#### 3層テスト構造

| 層 | ファイル | テスト数 | 内容 |
|---|---|---|---|
| ユニットテスト | 各 `src/*.rs` 内 `#[cfg(test)]` | 79 | 個別関数の入出力検証 |
| 統合テスト | `tests/*.rs` | 20 | CLI サブコマンドの E2E 検証 |
| ベンチマーク | `benches/*.rs` | 3ファイル | criterion によるパフォーマンス測定 |

#### assert_cmd による CLI テスト

```rust
fn brv_cmd() -> Command {
    Command::cargo_bin("brv").unwrap()
}

#[test]
fn test_compile_builtin_conflict() {
    let dir = TempDir::new().unwrap();
    let config_path = create_config(&dir, r#"
[[abbr]]
keyword = "cd"
expansion = "custom_cd"
"#);

    brv_cmd()
        .args(["compile", "--config", config_path.to_str().unwrap()])
        .env("XDG_CACHE_HOME", dir.path().join("cache"))
        .assert()
        .failure()
        .stderr(predicate::str::contains("builtin"));
}
```

**学び**:
- `env("XDG_CACHE_HOME", ...)` でテスト用のキャッシュディレクトリを指定し、ユーザーの実環境を汚染しない
- `predicate::str::contains(...)` で出力の部分一致を検証 (完全一致は脆い)
- `TempDir` はスコープ終了時に自動削除される

#### compile → expand のE2Eテスト

```rust
fn setup_compiled(dir: &TempDir, config_content: &str) -> (PathBuf, PathBuf) {
    let config_path = dir.path().join("brv.toml");
    std::fs::write(&config_path, config_content).unwrap();

    // コンパイル実行
    Command::cargo_bin("brv").unwrap()
        .args(["compile", "--config", config_path.to_str().unwrap()])
        .env("XDG_CACHE_HOME", dir.path().join("cache"))
        .assert()
        .success();

    let cache_path = dir.path().join("cache").join("brv").join("brv.cache");
    (config_path, cache_path)
}
```

**学び**: compile → expand の2段階パイプラインは、ヘルパー関数で抽象化すると統合テストが書きやすい。

---

### 8. リリースビルド最適化

```toml
[profile.release]
strip = true      # デバッグシンボル除去
lto = "thin"      # リンク時最適化 (thin = コンパイル速度とのバランス)
opt-level = 3     # 最大最適化
codegen-units = 1 # 単一コンパイル単位 (最大最適化を可能にする)
```

結果: リリースバイナリ **2.1MB** (strip 前は ~5MB)。

**学び**: `lto = "thin"` は `lto = true` (fat LTO) より高速にコンパイルでき、ほとんどのケースで同等のパフォーマンスを得られる。`codegen-units = 1` は最大最適化に必要だが、コンパイル時間が増加する。

## ポイント

- **事前コンパイルパターン**: 設定パースや検証などの重い処理を事前に行い、頻繁に呼ばれるパスではバイナリキャッシュを読むだけにする
- **bincode + serde**: Rust のデータ構造を derive だけで高速にシリアライズ/デシリアライズ
- **FxHashMap**: セキュリティが不要な内部ルックアップには FxHash が最速
- **config_hash**: ファイル内容のハッシュによる鮮度チェックは mtime より信頼性が高い
- **衝突検出**: 「デフォルト厳格、明示的に緩和」の安全設計パターン
- **ZLE 統合**: stdout 行ベースプロトコルでシェルとネイティブバイナリを疎結合にする
- **`#[cfg(unix)]`**: プラットフォーム固有コードは条件コンパイルで分離
- **テスト環境の隔離**: `env("XDG_CACHE_HOME", ...)` と `TempDir` でユーザー環境を汚染しない
- **ユーザー向けメッセージは英語**: CLI ツールは国際的に使われる前提で、エラーメッセージ・ヘルプ・コメントすべて英語にする

## 参考

- [zeno.zsh](https://github.com/yuki-yano/zeno.zsh) - Deno ベースの abbreviation ツール (比較対象)
- [zsh-abbr](https://github.com/olets/zsh-abbr) - 純粋 zsh 実装の abbreviation ツール (比較対象)
- [alias cc='claude' によるシステムハング事例](https://zenn.dev/owayo/articles/6190821ac1dd1e) - 衝突検出の動機となった実際の事故
- [rustc-hash (FxHash)](https://crates.io/crates/rustc-hash) - Firefox 由来の高速ハッシュ
- [bincode](https://crates.io/crates/bincode) - Rust バイナリシリアライザ
- [brv リポジトリ](https://github.com/ushironoko/brv)
