---
title: "高級言語が見せてくれなかったもの — キャッシュ・分岐予測・UB・メモリモデル(後編)"
status: plan
---

## 想定読者と前提

- 前編 `assembly_for_high_level_users_part1` を読み、「コンパイラがレジスタ・スタック・呼出規約を代行している」というメンタルモデルを獲得した中上級エンジニア
- 高級言語で日常業務は回っているが、以下のような経験があり「言語化したい」と感じている人:
  - アルゴリズム的には同じはずなのに、データの並べ方を変えただけで何倍も速くなった
  - `if` の中身を入れ替えただけで速度が変わった
  - `Release` ビルドだけバグった、`-O2` を付けたら壊れた
  - マルチスレッドで「ありえない順序」のバグを見た
  - Python から C 拡張、Go から `cgo`、Rust から C を呼んだら謎の clash が出た
- 前提知識: 前編のレジスタ / メモリ / 呼出規約のメンタルモデル

## この記事が答える問い

1. 高級言語があるのに、なぜ未だに低レイヤー知識が必要な瞬間があるのか
2. 「アルゴリズム的には同じ `O(n)`」なのに 5〜10 倍速度が違うのはなぜか
3. `undefined behavior` はなぜ「無害なバグ」ではなく「最適化に食われる爆弾」なのか
4. マルチスレッドで「ソースコードに書いた順序」が裏切られるのはどういう機構か
5. FFI(言語境界)で起こる典型バグはどう発生するのか
6. 結局、高級言語ユーザーはどこまで降りればいいのか

## 扱う / 扱わない

- **扱う**: Leaky Abstraction の典型 5 ケース(キャッシュ、分岐予測、UB、メモリモデル、ABI/FFI)、それぞれが「ソースコードを読むだけでは見えない」理由、降りる/降りないの判断基準
- **扱わない**: Spectre / Meltdown の完全解説、各 CPU の microarchitecture 詳細、C++ / Java / Go メモリモデル仕様の網羅、SIMD 命令カタログ、PGO / LTO の詳細

## セクション構成

### 1. 「Leaky Abstraction」を共通言語にする

- Joel Spolsky の "Law of Leaky Abstractions" を 30 秒で紹介
- どんな抽象化も**漏れる**。問題はどこから漏れるかと、漏れたときに何が見えるか
- 前編で見た「コンパイラの 3 つの代行」も、漏れるときがある。そのカタログを 5 つ並べるのが本記事

### 2. 性能の漏れ ① — キャッシュライン

- CPU はメモリを 1 バイトずつ読まない。**64 バイト単位(キャッシュライン)**でまとめて読む
- 配列を順番に舐めるコードと、ランダムアクセスするコードの速度差は、アルゴリズム計算量ではなく**キャッシュヒット率の差**
- 「Array of Structs vs Struct of Arrays」を 1 段落だけ
- マルチスレッドでは **False Sharing** という別の落とし穴がある
  - スレッド A が `counter_a` を更新、スレッド B が `counter_b` を更新、論理的には独立。だが**同じキャッシュラインに乗っていると**お互いのキャッシュを無効化し合い、シリアル実行より遅くなる
  - 対策: `alignas(64)` でキャッシュライン境界に揃える
- 高級言語ユーザーへの含意: 「`HashMap` を `Vec<Pair>` に置き換えただけで速くなる」ような現象の正体はここ
- 根拠: aussieai.com/blog/false-sharing, dev.to/ariasdiniz/.../false-sharing, linkedin.com/.../yahav-gabay/false-sharing

### 3. 性能の漏れ ② — 分岐予測 / 投機実行

- 現代 CPU はパイプライン化されており、命令を「**結果が出る前に先取りして実行する**」
- 条件分岐に出会うと、CPU は「どちらに飛ぶか」を**予測**して投機的に実行を進める
- 予測が当たれば速い。外せば**パイプラインを捨てて巻き戻す**ペナルティ(数十サイクル)
- StackOverflow 古典「ソート済みの配列を処理するほうが速い」の正体
- バイナリサーチがメモリ律速のとき、**分岐予測が外れても OOO 実行で待ち時間を埋められる**(=「分岐ミス=即遅い」ではない)というニュアンスも添える
- 高級言語ユーザーへの含意:
  - データを事前にソートすると劇的に速くなる場合がある
  - ホットパスからの `if` の除去(branchless 化)が有効な場合がある
  - JIT / AOT がやっているプロファイル誘導最適化(PGO)の動機もここ
- 根拠: en.wikipedia.org/wiki/Branch_predictor, johnnysswlab.com/.../branches-influence-performance

### 4. 意味論の漏れ ① — undefined behavior

- C/C++ の UB は「ランタイムエラー」ではない。**「何が起きても文句は言えない」**という規約上の白紙小切手
- Russ Cox の有名な例: `Do` という関数ポインタが null かもしれない。コンパイラは「null 呼び出しは UB だから、null でないと仮定してよい」「`Do` が `EraseAll` 以外には絶対ならないと推論できる」「ならば `Do()` は `EraseAll()` に直接置き換えてよい」とし、結果として`system("rm -rf slash")` が**常に実行されるバイナリ**を吐く
- Regehr の整理:「UB は最適化の余地として消費される」「`-O0` で動いていたコードが `-O2` で挙動が変わるのは、UB を踏んでいることが多い」
- 高級言語ユーザーへの含意:
  - C/C++ や Rust の unsafe ブロックを書く瞬間、**ソースコードの素直な意味論はもう信用できない**
  - 「動いているように見えるから OK」は最も危険な反応
  - Rust の safe 範囲、JVM、CPython、Go のような managed 言語は、この爆弾を「踏ませない」ことに価値がある
- 根拠: blog.regehr.org/archives/1520, research.swtch.com/plmm, web.ist.utl.pt/nuno.lopes/pubs/ub-pldi25.pdf, people.csail.mit.edu/nickolai/papers/wang-stack.pdf

### 5. 意味論の漏れ ② — メモリモデル(並行性)

- 並列スレッドの世界では、「ソースコードに書いた順序」も「コンパイラがアセンブリに翻訳した順序」も、**他スレッドから見たときに守られる保証は無い**
- 3 段の並べ替え:
  1. コンパイラの最適化が命令を入れ替える
  2. CPU が out-of-order に実行する
  3. キャッシュ間の伝播順序が逆転する
- 「順次一貫性 (sequential consistency)」を諦め、**acquire / release / relaxed** という細かい契約で書き手が必要なバリアだけ宣言するのが、現代の言語メモリモデル(C++11, Java, Go, Rust)
- 「Store Buffering」のような最小例を 1 つ:
  ```
  // x, y は初期 0、別スレッドで以下を同時実行
  Thread A: x = 1; r1 = y;
  Thread B: y = 1; r2 = x;
  ```
  - 直感的には「`r1 == 0 && r2 == 0`」はあり得ないように見えるが、**実機で観測できる**
- 高級言語ユーザーへの含意:
  - 「ロック無しで `flag = true` してから値を書いた」は危ない
  - 言語の `atomic` / `volatile` / `Mutex` の意味は単なる「壊さない」ではなく、**メモリオーダリングのバリア**を含む
  - Python の GIL は「この問題を多くの場面で踏ませない」装置でもあった(前作と接続)
- 根拠: research.swtch.com/plmm(Russ Cox の標準的レファレンス)

### 6. 境界の漏れ — ABI / FFI バグ

- 前編で見たとおり、呼出規約は **OS と ISA の組み合わせ**で違う
- 言語境界(FFI)で踏みやすい罠:
  - 構造体パディング / アライメントの食い違い
  - `int` のサイズが言語間で違う(C の `long` は Windows 64-bit で 32 ビット、Linux 64-bit で 64 ビット)
  - 呼出規約の取り違え(`stdcall` vs `cdecl` 時代の遺物、Windows COM/Win32 API は今でも `__stdcall` を要求する)
  - 構造体の戻り値:8 バイト超や非 POD はレジスタで返らず、**呼出元が確保した領域へのポインタ**経由になる(Microsoft x64 仕様)
  - `errno` / TLS / 例外伝搬の取り扱い
- 「Rust から C を呼んで何故か落ちる」「Python ctypes でセグフォる」のいくつかは、**ソースコードを正しく書いていても**この境界で死んでいる
- 高級言語ユーザーへの含意: FFI を書く瞬間、前編で見た ABI の話を**自分でやる側**に回らされている
- 根拠: 前編で使ったのと同じ ABI 公式群

### 7. まとめ — いつ降りるべきか / いつ降りなくていいか

「アセンブラを読めるようになれ」と煽る記事にはしない。逆に、**降りなくていい場面の方が圧倒的に多い**ことを明示する。

**降りなくていい**(=高級言語の中で完結):
- アプリケーションロジック、CRUD、ビジネスルール
- I/O bound のコード(DB / ネットワークが律速のとき)
- アルゴリズムレベルで遅い問題(`O(n²)` を `O(n log n)` にする方が桁違いに効く)

**降りる価値がある**:
- ホットパスで「アルゴリズム計算量は正しいのに速度が出ない」
- マルチスレッド / lock-free の正しさが要る
- C / C++ / Rust unsafe / FFI を書く瞬間
- `Release` ビルドだけ挙動が変わる、`-O0` と `-O2` で違う、`memcpy` 周辺で謎クラッシュ
- 言語境界でセグフォる / 値が化ける

ここで、前作 2 本 + 前編 + 本作の 4 部作で得た**抽象度の階段**を最後に図示してまとめる。

```
ソース(.py / .c / .rs / .go)
   ↓ (前作①)
バイトコード / IR
   ↓ (前作②)
ネイティブコード(アセンブリ・機械語)        ← 前編
   ↓ (本作)
CPU パイプライン / キャッシュ / メモリ階層    ← ここからは「ソースコードの順序」が
                                              そのまま守られない世界
```

## 使用予定の主要根拠

- en.wikipedia.org/wiki/Branch_predictor
- johnnysswlab.com/how-branches-influence-the-performance-of-your-code-and-what-can-you-do-about-it/
- blog.regehr.org/archives/1520(John Regehr "Undefined Behavior in 2017")
- web.ist.utl.pt/nuno.lopes/pubs/ub-pldi25.pdf(UB と最適化、PLDI 2025)
- people.csail.mit.edu/nickolai/papers/wang-stack.pdf(MIT, UB の影響分析)
- research.swtch.com/plmm(Russ Cox, Programming Language Memory Models)
- aussieai.com/blog/false-sharing, dev.to/ariasdiniz/.../false-sharing, linkedin.com/.../yahav-gabay/false-sharing(False sharing 実例)
- 前編で使った ABI 公式群(System V AMD64, Microsoft x64, AAPCS64)

## frontmatter(publish 用)案

```yaml
title: "高級言語が見せてくれなかったもの — キャッシュ・分岐予測・UB・メモリモデル"
emoji: "🪞"
type: "tech"
topics: ["assembly", "performance", "concurrency", "architecture", "lowlevel"]
published: false
```
