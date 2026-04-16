# テストが爆発するデフォルト値 — DPのturn_limit定数化で学んだこと

## 概要

ゲーム木DPのturn_limitを定数化した際、デフォルト値が内部API経由でテストに漏れ、テストが10分超に爆発。
`sample` プロファイリングで原因特定し、3.7秒まで短縮した過程の記録。

## 背景・きっかけ

MoonBitのSwitchingGame DP (zero-sum Nash解き)で、
turn_limitをCLI境界の定数(20)にした。
テストが10分以上かかるようになり、一度もgreenを
確認できないまま何時間も経過。

## 学んだこと

### 1. 高価なデフォルト値はテストを破壊する

内部APIのデフォルト引数に`DP_TURN_LIMIT=20`を
埋めると、テストが明示しない限りその値で走る。
問題は3箇所で発生した:

- `select_input_json` ヘルパーが空の extra を渡す
  → CLIパーサーが既定 SwitchingGame(20) を選択
- `skill_smoke_test` が JSON に team_payoff_model 未指定
- screened oracle テストが labeled arg を渡し忘れ

**原則**: デフォルト値はCLI境界にだけ置く。
内部APIは明示引数を強制するか、
テスト用ヘルパーに軽量デフォルトを埋める。

### 2. macOS `sample` でネイティブバイナリをプロファイル

```bash
# 走行中のプロセスにアタッチして5秒間サンプリング
sample <PID> 5 -file /tmp/profile.txt

# ホットなソース行を集計
grep -o '[a-z_]*\.mbt:[0-9]*' /tmp/profile.txt \
  | sort | uniq -c | sort -rn | head -15
```

出力はコールグラフ形式で、ソースファイル名と
行番号が付く。Instruments不要でCLIだけで完結。
MoonBit nativeバイナリでも機能する。

### 3. HashMapのHash計算コスト

`derive(Hash)` で `Array[Int]` や `Array[Bool]` を
含む構造体をキーにすると、毎回全要素を走査する。
プロファイルでは `hasher.mbt` と
`arraycore_nonjs.mbt` が上位を占めていた。

DPの状態キャッシュでは、キーのハッシュ計算が
ボトルネックになりうる。対策候補:
- 状態を整数エンコードしてキーにする
- Zobrist hashing で差分ハッシュ

## ポイント

- テストが遅いとき、まず「どのテストが」を特定する（`-F` フィルタや `-f` ファイル指定で切り分け）
- `sample` は外部ツール不要でmacOS標準。3-5秒のサンプリングで十分
- デフォルト値の漏れはプロファイルなしでは発見困難。「どこの関数にいるか」をスタックで見る
