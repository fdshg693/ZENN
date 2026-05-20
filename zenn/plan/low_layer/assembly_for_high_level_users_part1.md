---
title: "アセンブラを書かない人のためのアセンブラ — 高級言語が抽象化した 3 つの問題(前編)"
status: plan
---

## 想定読者と前提

- 普段は Python / JavaScript / Go / Java / Rust / C# などの**高級言語**で仕事をしているエンジニア
- アセンブラは「見たことはあるが、書いたことも読んだこともない」レベル
- 学部の CPU 演習で `mov` `add` あたりは触ったが、その後 5〜10 年触っていない人を含む
- 「JIT」「コンパイラの最適化」「ネイティブコード」という言葉を毎日見るが、それが具体的に何を指しているのかを言語化できていない人

前提知識: 関数・スタック・ヒープ・ポインタという概念は名前を聞いたら分かるレベル。C や Go の読解までは要求しない。

## この記事が答える問い

1. 「アセンブラ」と「機械語」と「ISA」は同じものか。違うなら何が違うのか
2. `return a + b;` という 1 行を CPU は何ステップで実行しているのか
3. 同じ C コードが、x86_64 と AArch64 でどれくらい違うアセンブリになるのか
4. コンパイラが「関数呼び出し」を翻訳するときに、本当は何の取り決めを守っているのか(呼出規約 / ABI)
5. 高級言語が抽象化してくれているのは具体的にどんな作業なのか
6. なぜ「ポータブルなアセンブラ」は存在し得ないのか

## 扱う / 扱わない

- **扱う**: x86_64 と AArch64 の対比、Compiler Explorer の読み方、レジスタ / スタック / 命令ストリームという CPU の世界観、System V AMD64 と Microsoft x64 と AAPCS64 の呼出規約の最低限の対比、「コンパイラが代行している 3 つの作業」(レジスタ割付・スタックフレーム管理・ABI 遵守)
- **扱わない**: アセンブラ完全構文表、個別命令カタログ、SIMD / AVX-512 の細部、リンカ / ローダの内部、OS のシステムコール、JIT 実装、RISC-V(分量都合)

## セクション構成

### 1. 前作 2 本との接続 — VM の下、C 拡張のさらに下

- 前作 `python_bytecode_internals` で「VM の評価ループ」まで降りた
- 前作 `python_c_extensions_internals` で「C で書かれた関数本体」まで降りた
- 本作はその C 関数が「実際に CPU に渡る形」=ネイティブコードとは何かを扱う
- 高級言語ユーザーにとって、「ここから先」を読めなくても日常業務は回る。だがパフォーマンス事故とメモリバグの一部は、ここを読まないと潰せない

### 2. 「アセンブラ」と「機械語」と「ISA」を分ける

- 機械語: CPU が直接食えるバイト列
- アセンブラ言語: その機械語に**ほぼ 1 対 1** で対応する、人間が読み書きできる表記
- ISA(命令セットアーキテクチャ): CPU が「何という命令を受け付けるか」という契約。x86_64 / AArch64 / RISC-V / ...
- 高級言語が「言語」なら、アセンブラは「**ISA の表記法**」。これが ISA ごとに違う理由
- 根拠: xania.org/202506/how-compiler-explorer-works(Godbolt 本人)

### 3. CPU が見ている世界 — レジスタ / メモリ / 命令ストリーム

- 高級言語の「変数」は嘘で、CPU から見えるのは **レジスタとメモリだけ**
- レジスタは「CPU 内部の数十個の超高速スロット」
- 命令はメモリ上のバイト列として並んでおり、`PC`(命令ポインタ)が次に実行する命令を指している
- 「制御フロー」は `PC` の書き換え、「変数代入」はレジスタかメモリへの書き込み、「関数呼び出し」は `PC` の保存付きジャンプ
- ここで一度、Python の `LOAD_FAST` などのバイトコードと、x86_64 の `mov` を**抽象度の階段**として並べて見せる

### 4. `return a + b;` を Compiler Explorer で覗く

- Compiler Explorer(godbolt.org)で `int add(int a, int b) { return a + b; }` を gcc x86_64 と clang AArch64 で並べる
- x86_64(System V): 引数は `edi` / `esi`、戻り値は `eax`、3 命令ほどで終わる
- AArch64: 引数は `w0` / `w1`、戻り値は `w0`
- 同じ意味の C コードが、ISA が違うだけで命令もレジスタ名も別物になる(=「ポータブルなアセンブラ」が存在し得ない)
- ここで「最適化オプション `-O2` を付けると無駄な `mov` が消える」も見せ、**コンパイラはコードを書き換える**という事実を提示
- 根拠: xania.org の Godbolt 記事、cs61.seas.harvard.edu/site/2018/Asm2/

### 5. 高級言語が抽象化した「3 つの仕事」

ここが記事の中核。中級エンジニアが「コンパイラ任せにしてきたもの」を明文化する。

#### 5.1 レジスタ割付(Register Allocation)

- 変数は無限に作れるが、レジスタは数十個しかない
- どの変数をどのレジスタに「住まわせる」か、いつメモリに退避(spill)するかを決めるのがコンパイラの仕事
- 高級言語ユーザーが「変数を増やしてもタダ」と感じられるのはコンパイラがこれをやっているから

#### 5.2 スタックフレームの管理

- 関数呼び出しのたびに、戻り先アドレス・ローカル変数・退避レジスタを置く領域(スタックフレーム)を確保・破棄する
- x86_64 では `%rsp` が指すアドレスがスタックの先端。**スタックは下方向に伸びる**
- 16 バイトアラインを守る義務、`call` 命令時の `%rsp` は「16 の倍数から 8 バイトずれた値」になるなど、機械的な制約が大量にある
- 高級言語ユーザーは関数を呼ぶだけ。だが裏ではコンパイラがこの会計係を 100% 代行している
- 根拠: cs61.seas.harvard.edu/site/2018/Asm2/

#### 5.3 呼出規約 / ABI の遵守

- 「関数を呼ぶ側」と「呼ばれる側」が、引数をどのレジスタ / スタック位置に置くか、戻り値はどこか、どのレジスタを破壊してよいかを**事前に合意**しておく必要がある
- これが**呼出規約 (calling convention)** であり、より広く ABI(Application Binary Interface)の一部
- 同じ x86_64 でも、Linux/macOS は **System V AMD64**、Windows は **Microsoft x64** で**別物**
- AArch64 は **AAPCS64**(Arm の Procedure Call Standard)

### 6. 呼出規約 3 種を表で並べる

最低限の対比表だけ提示する(詳細は記事の主旨ではない)。

| 項目 | System V AMD64 (Linux/macOS) | Microsoft x64 (Windows) | AAPCS64 (AArch64) |
|---|---|---|---|
| 整数引数レジスタ | `rdi, rsi, rdx, rcx, r8, r9`(最大6) | `rcx, rdx, r8, r9`(最大4) | `x0`〜`x7`(最大8) |
| 戻り値 | `rax`(+`rdx`) | `rax` | `x0`(+`x1`) |
| caller-saved 例 | `rax, rcx, rdx, rdi, rsi, r8-r11` | `rax, rcx, rdx, r8-r11` | `x0-x15` |
| callee-saved 例 | `rbx, rbp, r12-r15` | `rbx, rbp, rdi, rsi, r12-r15` | `x19-x28` |
| 特殊事情 | red zone(関数末尾 128 バイト) | shadow space(呼出元が 32 バイト確保) | `sp` 16 バイトアライン |

- ここで「**Windows と Linux で同じ x86_64 なのに、`rdi` で渡すか `rcx` で渡すかが違う**」という事実が、後編の「ABI/FFI バグ」の伏線になる
- 根拠: refspecs.linuxbase.org/elf/x86_64-abi-0.99.pdf, learn.microsoft.com/en-us/cpp/build/x64-calling-convention, en.wikipedia.org/wiki/X86_calling_conventions, developer.arm.com/documentation/102374/0103/Procedure-Call-Standard

### 7. まとめ — 高級言語は「CPU との対話」を抽象化した言語である

- 高級言語が解決した問題:
  - ISA ごとに書き直さなくてよい(ポータビリティ)
  - レジスタ・スタック・呼出規約を意識しなくてよい(認知負荷)
  - 同じ意味のコードが、同じソースで Windows でも Linux でも動く(配布性)
- ただし、これは「無料」ではない。コンパイラが介在することで、**ソースコードと実際に走るネイティブコードのあいだに「意味のズレ」が生まれる**
- そのズレが業務に効いてくる場面を、次の後編で扱う

## 後編への接続

- 後編タイトル仮: 「高級言語が見せてくれなかったもの — キャッシュ・分岐予測・UB・メモリモデル」
- 後編で扱う 5 トピック:
  1. キャッシュライン
  2. 分岐予測 / 投機実行
  3. undefined behavior と最適化
  4. メモリモデル(並行性)
  5. ABI / FFI バグ

## 使用予定の主要根拠

- xania.org/202506/how-compiler-explorer-works(Matt Godbolt 本人によるCE解説)
- refspecs.linuxbase.org/elf/x86_64-abi-0.99.pdf(System V AMD64 ABI 公式)
- learn.microsoft.com/en-us/cpp/build/x64-calling-convention(Microsoft x64)
- en.wikipedia.org/wiki/X86_calling_conventions(俯瞰)
- cs61.seas.harvard.edu/site/2018/Asm2/(Harvard CS 61 講義)
- developer.arm.com/documentation/102374/0103/Procedure-Call-Standard(Arm 公式 PCS)
- github.com/ARM-software/abi-aa/releases(AAPCS64 仕様の最新リリース)

## frontmatter(publish 用)案

```yaml
title: "アセンブラを書かない人のためのアセンブラ — 高級言語が抽象化した 3 つの問題"
emoji: "🔧"
type: "tech"
topics: ["assembly", "compiler", "lowlevel", "performance", "architecture"]
published: false
```
