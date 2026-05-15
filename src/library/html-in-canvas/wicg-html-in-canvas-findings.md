# WICG html-in-canvas PoC を実機検証して得た知見

## 概要

[WICG html-in-canvas](https://github.com/WICG/html-in-canvas) を Chrome Canary の `#canvas-draw-element` フラグ有効環境で実機検証し、experimental 実装の SIGSEGV トリガー条件、`texElementImage2D` を安定動作させるためのアーキテクチャ、ガラス／立体テキスト表現の WebGL シェーダーパターンを得た。

## 背景・きっかけ

HTML 要素を `<canvas>` のテクスチャとして取り込み、WebGL シェーダーで自由なエフェクト (歪み、屈折、3D 化) を乗せられる API として WICG が提案している実験的 API を PoC レベルで触り、Liquid Text 風 / Glass Card 風 / 3D Material 風の 3 ページを作る過程で多数のクラッシュと挙動差に遭遇した。仕様上は許容されているはずの DOM 構成で Chromium レンダラ/GPU プロセスが SIGSEGV を起こすケースが複数あり、回避するための DOM 構造制約とシェーダーの組み方を整理する。

## 学んだこと

### Chromium experimental 実装の SIGSEGV (exit code 11) トリガー条件

`chrome://flags/#canvas-draw-element` 有効環境 (Chrome Canary) で、以下 3 パターンを再現的にクラッシュさせた。いずれも spec を読む限り合法な書き方で起こるため、experimental 実装側のバグと判断できる。

**1. `<canvas layoutsubtree>` の direct child が子要素を持たない (空要素)**

```html
<!-- NG: direct child の div が完全に空 -->
<canvas layoutsubtree>
  <div ref="bgEl" style="background: #1e1b4b" />
</canvas>

<!-- OK: 中に何か element child を 1 つ仕込む -->
<canvas layoutsubtree>
  <div ref="bgEl" style="background: #1e1b4b">
    <span style="display: block; width: 1px; height: 1px">&nbsp;</span>
  </div>
</canvas>
```

`&nbsp;` などのテキストノードだけでは不十分で、`element child` を含む必要があった。

**2. canvas 自身を `position: absolute` で配置する**

```css
/* NG: canvas[layoutsubtree] を absolute で重ねる */
.canvas {
  position: absolute;
  inset: 0;
}
```

canvas は flow に置き、必要なオーバーレイは canvas の兄弟要素として absolute に配置する設計に切り替えると安定した。

**3. direct child のサブツリー内に `position: absolute` の要素を含める**

`canvas[layoutsubtree]` のサブツリー全体に対して `position: absolute` の制約が及ぶ。装飾図形 (円、矩形) を absolute で重ねる伝統的な背景パターンは使えない。

```html
<!-- NG: bg div の中に absolute 配置の子要素 -->
<canvas layoutsubtree>
  <div class="absolute inset-0">
    <div style="position: absolute; top: 15%; left: 10%; ..."></div>
  </div>
</canvas>

<!-- OK: 装飾は multi-layer CSS gradient で表現 -->
<canvas layoutsubtree>
  <div
    class="absolute inset-0"
    style="
      background:
        radial-gradient(circle 140px at 22% 32%, rgba(96,165,250,0.65) 0%, transparent 70%),
        radial-gradient(circle 160px at 78% 74%, rgba(59,130,246,0.55) 0%, transparent 70%),
        linear-gradient(135deg, #000 0%, #1e3a8a 100%);
    "
  >
    <span>&nbsp;</span>
  </div>
</canvas>
```

`canvas[layoutsubtree]` 自身が absolute なのは NG だが、direct child の `<div class="absolute inset-0">` は OK (Liquid Text と Glass Card 両方で確認)。崩れるのは direct child の **さらに子孫** での absolute 配置。

### html-in-canvas + WebGL2 を安定動作させるアーキテクチャ

仕様だけ読むと、毎フレーム `canvas.requestPaint()` を呼んで `onpaint` 内で `texElementImage2D` する rAF 連動が自然に見える。実際これで動くが、experimental 実装ではほぼ確実に途中で暴走する (画面更新が止まる/プロセスが死ぬ)。

安定動作させるには **paint イベントと描画ループを分離する** のが鍵だった。

```ts
// NG: 毎フレーム requestPaint + 毎フレーム texElementImage2D
canvas.onpaint = () => {
  gl.texElementImage2D(target, 0, fmt, fmt, type, element); // 毎回呼ばれる
  drawWithUpdatedUniforms();
};
function loop() {
  canvas.requestPaint();
  requestAnimationFrame(loop);
}

// OK: paint は取り込みだけ、描画は rAF だけ
let textureReady = false;
canvas.onpaint = () => {
  gl.texElementImage2D(target, 0, fmt, fmt, type, element);
  textureReady = true;
};
function loop() {
  if (textureReady) drawWithUpdatedUniforms(); // テクスチャは静的キャッシュを再利用
  requestAnimationFrame(loop);
}
// 初回キックと、DOM 内容変更時 / canvas resize 時のみ
canvas.requestPaint();
```

ポイントは「テクスチャ取り込み (高コスト & experimental ロジック) を必要なときだけ走らせ、毎フレーム回す処理は uniform 更新 + drawArrays だけにする」こと。アニメーションは時刻ベースで uniform を進めれば成立し、テクスチャ自体は前回取り込んだ snapshot をそのまま使う。

DOM 変更時に再取り込みしたい場合は `textureReady = false; canvas.requestPaint();` を明示的に呼ぶ。canvas resize 時も同様。

### ガラス表現で使えるシェーダーテクニック

「カードの内側だけ背景が屈折して見える」ガラス表現を、テクスチャ + シェーダーだけで作る場合に効いた要素:

**SDF (Signed Distance Field) でカード形状を生成する**

カードのアルファマスクをテクスチャから取るのではなく、シェーダー内で `sdRoundedBox` を計算してマスクを作る。これにより:
- カード本体は DOM のままレンダリング (canvas の上に絶対配置) でき、ボタンクリック等の hit-testing が完全に生きる
- シェーダー側で生成したマスクと CSS 側のカード形状を一致させるには **canvas のアスペクト比補正** が必須

```glsl
uniform float u_aspect; // canvas width / height

float sdRoundedBox(vec2 p, vec2 b, float r) {
  vec2 d = abs(p) - b + vec2(r);
  return min(max(d.x, d.y), 0.0) + length(max(d, 0.0)) - r;
}

void main() {
  // 縦軸基準で正規化 (x は 0..aspect, y は 0..1) して等方空間で SDF 計算
  vec2 uvAspect = vec2(v_uv.x * u_aspect, v_uv.y);
  vec2 p = uvAspect - u_cardCenter;
  float dist = sdRoundedBox(p, u_cardHalfSize, u_cardRadius);
  float mask = 1.0 - smoothstep(0.0, 0.01, dist);
  // ...
}
```

座標を全部 UV (0..1, 0..1) で渡すとアスペクト比違いで rounded corner が縦長/横長に歪む。JS 側でも全長さを `wrapperRect.height` で割って正規化し、シェーダー内で x のみ aspect 倍に戻す。

**屈折は 2 種類を重ねる**

```glsl
// 凸レンズ風 (カード全域を中心方向へ引っ張る)
vec2 lensOffsetA = p * u_refraction * mask;
vec2 lensOffset = vec2(lensOffsetA.x / u_aspect, lensOffsetA.y);

// SDF 法線屈折 (エッジ近傍だけ強い)
float eps = 0.002;
float dx = sdRoundedBox(p + vec2(eps, 0.0), b, r) - sdRoundedBox(p - vec2(eps, 0.0), b, r);
float dy = sdRoundedBox(p + vec2(0.0, eps), b, r) - sdRoundedBox(p - vec2(0.0, eps), b, r);
vec2 normalA = vec2(dx, dy) / (2.0 * eps); // central differences で normalize
vec2 normalUv = vec2(normalA.x / u_aspect, normalA.y);
float edgeBand = smoothstep(-0.05, 0.0, dist) * step(dist, 0.0);
vec2 edgeOffset = normalUv * u_refraction * edgeBand * 0.5;

vec2 totalOffset = lensOffset + edgeOffset;
```

法線を `vec2(dx, dy)` のまま使うと magnitude が `2 * eps` (≒ 0.004) と小さく屈折がほぼ見えない。`2 * eps` で割って正規化することで magnitude を 1 にする。

**色収差 (chromatic aberration)**

```glsl
float ca = u_refraction * 0.5 * mask;
vec2 uvR = v_uv - totalOffset * (1.0 + ca);
vec2 uvG = v_uv - totalOffset;
vec2 uvB = v_uv - totalOffset * (1.0 - ca);

vec3 blurredG = sampleBlur(uvG);
float r = texture(u_bg, uvR).r;
float b = texture(u_bg, uvB).b;
vec3 chromatic = mix(blurredG, vec3(r, blurredG.g, b), 0.7 * mask);
```

ぼかし基準は G、R/B はシャープサンプルにすると CA が視覚的に分かりやすい。

**Fresnel rim と specular highlight**

```glsl
// Fresnel: エッジに向かって反射が強くなる (edgeProx=0=エッジ, 1=中心)
float edgeProx = clamp(-dist * 12.0, 0.0, 1.0);
float fresnel = pow(1.0 - edgeProx, 4.0) * step(dist, 0.0);
glass += vec3(fresnel) * 0.35;

// 固定光源の specular
vec3 lightDir = normalize(vec3(-0.6, -0.7, 0.5));
vec3 surfNormal = normalize(vec3(-normalA * 3.0, 1.0)); // SDF 法線を 3D 化
float spec = pow(max(dot(surfNormal, lightDir), 0.0), 32.0) * edgeBand * 0.8;
glass += vec3(spec);
```

Fresnel の式は (1 - edgeProx) を pow するだけにする。これを `1.0 - pow(1 - edgeProx, 4.0)` のように二重反転にすると中心が最も光って見えるバグになる (一度踏んだ)。

### Layered Extrusion で立体テキスト

extrude (押し出し) ジオメトリを真面目に作るには文字 path や SDF が必要だが、html-in-canvas のテクスチャ機能だけでそれっぽい立体テキストを作れる:

1. 透明背景の DOM に大きな文字だけ置いてテクスチャ化
2. 同一テクスチャを z 方向に N 枚スタックして描画
3. フラグメントシェーダーで `if (c.a < u_alphaCutoff) discard;`
4. `CULL_FACE` を無効化して両面表示

```ts
function buildExtrudedText(aspect: number, layers: number, depth: number, roundness: number) {
  const w = aspect / 2;
  const h = 0.5;
  const verts: number[] = [];
  for (let i = 0; i < layers; i++) {
    const t = layers === 1 ? 0.5 : i / (layers - 1);
    const z = -depth / 2 + depth * t;
    // 中央 layer ほど大きく、両端 layer ほど縮小 (sin で枕状)
    const scale = 1 - roundness * (1 - Math.sin(Math.PI * t));
    const sw = w * scale;
    const sh = h * scale;
    verts.push(
      -sw, -sh, z, 0, 1, 0, 0, 1,
       sw, -sh, z, 1, 1, 0, 0, 1,
      -sw,  sh, z, 0, 0, 0, 0, 1,
      -sw,  sh, z, 0, 0, 0, 0, 1,
       sw, -sh, z, 1, 1, 0, 0, 1,
       sw,  sh, z, 1, 0, 0, 0, 1,
    );
  }
  return new Float32Array(verts);
}
```

各 layer の xy スケールを `1 - roundness * (1 - sin(πt))` で補間すると、横から見たときに **中央が膨らんだカプセル/レモン状の立体テキスト** になる。`roundness = 0` で従来の真っ直ぐな押し出し、増やすほど中央が膨らむ。

注意点:
- layer 数が多いほど overdraw + discard が増えて GPU 負荷が上がる。128 / 256 layer はインタラクション中にカクつくこともある。
- `CULL_FACE` は extrudedText のときだけ無効化する。cube などでは有効に戻して裏面 culling を効かせないと面の重なりがおかしくなる。
- 文字テクスチャ取り込み元の DOM は背景を `transparent` にしておかないと alpha cutoff の discard が効かず厚みが見えない。

### クラッシュデバッグの方法論

experimental API のクラッシュは StackTrace が取れないので、「動く最小版」と「落ちる版」の DOM/JS/シェーダー差分を **1 要素ずつ bisect** するのが最速だった。

セッションでの実例:
1. フル機能版が SIGSEGV → 動く最小版 (canvas + 単色 div + 単純シェーダー) まで段階的に削る
2. 動く最小版を基準に、**1 つだけ**戻して再現するか確認:
   - bg を `<div>` から `<h1>` に変える → 動いた
   - bg は `<div>` のまま兄弟要素にカード DOM を追加 → 動いた
   - bg の中に absolute 配置の子図形を追加 → クラッシュ
3. クラッシュ要因が「サブツリー内の absolute」と判明したら、回避策 (CSS gradient で装飾を表現) に切り替える

bisect の各ステップで「動く / 落ちる」だけを判断材料にし、推測で複数を同時に変えない。複数同時に戻すと、後で「実は別の要因も絡んでいた」場合に判断を誤る。

WICG/Chromium の experimental デモが動くかも併せて確認すると、環境問題かコード固有問題かの切り分けに役立つ。

## ポイント

- `<canvas layoutsubtree>` の direct child は **必ず element child を 1 つ以上持たせる**。空 div / span だけだとクラッシュ。
- `canvas[layoutsubtree]` 自身は **flow に置く**。absolute 配置は NG。
- direct child のサブツリー内では **`position: absolute` を使わない**。装飾は CSS multi-layer gradient で代替。
- `onpaint` は texture 取り込み専用。**描画ループは rAF + uniform 更新だけ**にして毎フレーム `requestPaint` は呼ばない。
- SDF を使う場合は **canvas のアスペクト比補正**を忘れない (縦軸基準で正規化)。
- SDF 法線屈折は **central differences の magnitude を正規化** しないと効果が見えない。
- Layered extrusion + sin(πt) で xy スケール補間すると、テクスチャだけで立体テキストの **丸み**を表現できる。
- experimental API のデバッグは **動く最小版からの bisect** が最速。

## 参考

- [WICG/html-in-canvas](https://github.com/WICG/html-in-canvas)
- [WICG html-in-canvas WebGL demo](https://wicg.github.io/html-in-canvas/Examples/webGL.html)
- [Chrome flags: canvas-draw-element](chrome://flags/#canvas-draw-element)
- [Inigo Quilez - distance functions](https://iquilezles.org/articles/distfunctions2d/) (sdRoundedBox の式)
