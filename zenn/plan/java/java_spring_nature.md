---
title: "JavaとSpringを「制御をランタイム/コンテナに渡す設計」として読む — 他言語経験者のための本質と制約"
status: plan
---

## 想定読者と前提

- Go / Python / Rust / TypeScript などで設計レベルまで理解しているが、**Javaだけは触ったことがない**中〜上級エンジニア
- 言語機能(型・例外・GC・並行)やWebフレームワークの一般論はすでに分かっている前提
- 「なぜJVMなのか」「Springのあの "magic" は何で、何を制約するのか」を**原理のレベルで**言語化したい人

## この記事の立場

- 文法・APIの書き方・チュートリアルには触れない(`for`の書き方や`@RestController`の使い方は説明しない)
- 「本質的な差分・設計上の制約・Springの特徴」に集中する
- 他言語/フレームワーク(Go / Python / Rust / FastAPI / Rails 等、知名度のあるもの)と積極的に対比して、経験者の既存知識に接続する
- コード例は差分が見える最小限のみ

## 一本の問い(thesis)

> **Java/Springの本質は「制御をランタイムとコンテナに手渡す」こと。**
> まず JVM という管理ランタイムにメモリ・実行・移植性の制御を預け、その上で Spring の DI コンテナに**アプリの配線とライフサイクルそのもの**を預ける。
> 代償は「間接性(magic)」と起動の重さ・リフレクション依存であり、近年の native image / Spring AOT / Virtual Threads はその代償への**揺り戻し**として読める。

各セクションは、この一本の問いの帰結として配置する。

## 記事で答える問い

1. なぜ「言語Java」ではなく「JVMというプラットフォーム」として捉えるべきか
2. 公称型・型消去・チェック例外・後方互換は何を保証し、何を強いるのか
3. Springの DI コンテナは他言語の DI と何が本質的に違うのか
4. アノテーション+プロキシの "magic" はなぜ生じ、どんな制約を必然的に生むのか
5. 自動構成(クラスパスから推測)の正体と、予測可能性とのトレードオフは何か
6. その代償と、native/AOT/Loom という揺り戻しはどう読めるか

## バージョン前提(2026-05時点・本文に明記)

- Java: **JDK 25 が最新LTS**(2025-09 GA、Premier Support 2030まで)。LTSは 8/11/17/21/25、次は29(2027予定)。6か月リリース + LTS。JDK 26 は 2026-03 GA(非LTS)。
- Spring: **Spring Boot 4.0.0(2025-11 GA)** が現行世代。Spring Framework 7.0 ベース、Java 25 フォーカス。3.5/3.4 系も保守対象。
- 根拠: oracle.com/java/technologies/java-se-support-roadmap.html, spring.io/blog/2025/11/13/..., spring.io/blog/2025/11/20/spring-boot-4-0-0-available-now

---

## セクション構成(plan)

### 0. イントロ — JavaとSpringを「性質」で読む

- 他言語は分かるがJavaは初めて、という読者に向けて、文法でなく**設計の重心**を渡す。
- thesis提示:「制御をランタイム(JVM)とコンテナ(Spring)に渡す」。記事はこの一本で貫く。
- 3層で読む:(a)JVMという土台が何を引き受けるか、(b)その上でSpringが何を引き受けるか、(c)その代償と揺り戻し。

---

## Part I — 土台としての Java / JVM

### 1. Javaは「言語」ではなく「JVMという管理ランタイムへの約束」

- **主張**: Javaの本質の半分はJVM。ソースは bytecode にコンパイルされ、JVMが実行・最適化・メモリ管理を所有する。「一度書けばどこでも動く」は、制御をランタイムに渡す対価として得た移植性。
- HotSpot は **まずインタプリタで実行し、profiling で "hot" と判定したメソッドだけ JIT(C1/C2)でネイティブ化**する。tiered compilation(Tier0インタプリタ→Tier4最適化)。JITは投機的で、前提が崩れれば deopt して下位 tier に戻れる。
- 帰結:「起動は遅く、暖機後に速い」。長時間稼働サーバに最適化された実行モデル(→Part IIIの native/起動コストへ伏線)。
- **対比**: Go/Rust は AOT でネイティブバイナリ(起動即ピーク、暖機なし)。Python は CPython バイトコード+インタプリタ(JITは任意)。JVMは「実行時に賢くなる」方に賭けた。
- 根拠: openjdk.org/groups/hotspot/docs/RuntimeOverview.html, docs.oracle.com/javacomponents/jrockit-hotspot/migration-guide/comp-opt.htm, openjdk.org/projects/leyden/...(tiered/speculative), openjdk.org/jeps/8335368(AOT)
- 根拠ファイル: extract_jvm_platform.json

### 2. 型は公称(nominal)で、ジェネリクスは実行時に消える

- **主張**: Javaの型は **公称的(nominal)**。`implements`を明示しない限り、構造が一致しても別物。
- **対比(公称 vs 構造)**: Go のインタフェースは構造的・暗黙満足(メソッドが揃えば実装したことになる)。Java は明示的に名前で結ぶ。Spring が「インタフェースに対してプログラムせよ」と推す土台でもある。
- **ジェネリクスは型消去(type erasure)**:「型消去により、パラメータ化型に対して新しいクラスは作られず、ジェネリクスは実行時オーバーヘッドを持たない」「`List<String>`と`List<Number>`をJVMは実行時に区別できない(non-reifiable)」。
- **対比**: Rust/C# は monomorphization/reified generics で実行時にも型が残る。Javaは互換性のため「コンパイル時だけの型」を選んだ → Springが実行時にリフレクションで型を補うのと地続き(後のセクションへ)。
- **プリミティブはオブジェクトではない**: `int`等はオブジェクトでなく、autoboxingでInteger等に変換。「すべてがオブジェクト」ではない(Pythonとの差)。
- 根拠: dev.java/learn/generics/type-erasure, docs.oracle.com/javase/tutorial/java/generics/nonReifiableVarargsType.html, docs.oracle.com/javase/tutorial/java/data/autoboxing.html
- 根拠ファイル: extract_type_system.json

### 3. チェック例外と「壊さない」という約束 — 型と互換性が引き受ける制御

- **主張**: Javaは失敗の一部を**型シグネチャ(throws)に乗せ、コンパイラが catch-or-specify を強制**する稀な言語。「クライアントが回復を期待できるなら checked、できないなら unchecked」。
- **対比**: Go は例外でなく明示的な `error` 返却。Rust は `Result<T,E>` + `?`。Python は全例外が unchecked。Javaのチェック例外は「失敗を握りつぶせない」保証と、冗長さ・`throws`汚染のトレードオフ(Springは多くを `RuntimeException` に倒して回避している事実にも触れる)。
- **後方互換という宗教**:「JDK8で動くなら、サポートされたAPIを使う限りJDK9以降でも動く」。6か月リリース+LTS、JEPプロセス、Maven Central の成熟。これがJavaの最大の「勝ち筋」=長期保守・大規模チームでの予測可能性。
- 根拠: docs.oracle.com/javase/tutorial/essential/exceptions/catchOrDeclare.html, .../runtime.html, docs.oracle.com/javase/specs/jls/se16/html/jls-11.html, docs.oracle.com/en/java/javase/11/migrate/index.html(互換), oracle.com/java/technologies/java-se-support-roadmap.html, openjdk.org/jeps/1
- 根拠ファイル: extract_checked_exceptions.json, extract_compat_ecosystem.json

---

## Part II — 土台の上の Spring(コンテナ)

### 4. Springの本質 — DIコンテナがオブジェクトの生死を所有する

- **主張**: Springの核は IoC コンテナ。「bean = コンテナによって instantiate / assemble / manage されるオブジェクト」。`ApplicationContext` がオブジェクトグラフの生成・配線・ライフサイクルを所有する。
- 既定は **singleton スコープ**:「定義につき1インスタンス、キャッシュされ、以降の参照はキャッシュを返す」。`ApplicationContext` は既定で singleton を **事前生成(eager pre-instantiation)**。ライフサイクルコールバック(`@PostConstruct`/`InitializingBean`)はコンテナの singleton creation lock 内で走る。
- **対比(ここが肝)**: DI自体は他言語にもある。FastAPI の `Depends` は**リクエスト単位の関数合成**、Go は wire 等の**明示配線でコンテナを持たない**文化。Springの差は「**中央集権・全部入り・ライフサイクル所有**」であり、Reactが coordinator を中央に置くのと同型の賭け(=複雑性をコンテナ側が吸収する代わりに、利用者はコンテナの作法に従う)。
- 根拠: docs.spring.io/spring-framework/reference/core/beans/introduction.html, .../factory-scopes.html, .../factory-nature.html
- 根拠ファイル: extract_spring_ioc_core.json

### 5. "magic" の正体 — アノテーション + 実行時プロキシ + リフレクション

- **主張**: `@Transactional`等の宣言的機能は**実行時プロキシ**で実現される。「Spring AOP は既定で JDK 動的プロキシ。インタフェースを実装しないクラスには CGLIB(実行時生成のサブクラス)」。weaving は実行時。
- **原理から導く制約**(本セクションの山場):
  - 「**プロキシの性質上、対象オブジェクト内部からの自己呼び出し(self-invocation)は定義上インターセプトされない**」→ `@Transactional`メソッドを同じクラスの別メソッドから呼ぶと効かない、の正体。
  - `final` メソッド/クラスは CGLIB で advise 不可。原則 `public` 経由。
  - スタックにプロキシが挟まる/デバッグが深くなる理由もここから。
- **対比**: これはコンパイル時マクロ(Rust の derive、Go の code generation)や Python のデコレータとは別物の **実行時メタプログラミング**。リフレクション+プロキシで「後付けで振る舞いを織り込む」。柔軟さの対価が、静的解析しづらさと起動時コスト(→Part IIIへ直結)。
- 根拠: docs.spring.io/spring-framework/reference/core/aop/introduction-proxies.html, .../aop/proxying.html, .../aop/ataspectj/pointcuts.html(self-invocation), .../aop-api/pfb.html
- 根拠ファイル: extract_spring_proxy.json

### 6. 規約と自動構成 — クラスパスから状態を「推測」する

- **主張**: `@EnableAutoConfiguration` は「**追加されたjar依存から、どう構成したいかを "推測(guess)" する**」。`@ConditionalOnClass`/`@ConditionalOnMissingBean` 等で「クラスがある時/自分でBeanを定義していない時だけ」適用。starter は依存の束。
- non-invasive:「自分で `DataSource` Beanを定義すると、既定の組み込みDBは引っ込む」。`--debug` で conditions report により「何がなぜ効いたか」を出せる。
- **対比**: Rails の convention over configuration と同系。Go/FastAPI は明示志向。Springは「**クラスパスに何があるか**」を暗黙の入力にして爆速立ち上げを得るが、対価は「暗黙の構成」=予測可能性とのトレードオフ。これが Part III の native image と正面衝突する伏線(動的に推測する設計は静的解析と相性が悪い)。
- 根拠: docs.spring.io/spring-boot/reference/using/auto-configuration.html, .../features/developing-auto-configuration.html
- 根拠ファイル: extract_autoconfig.json

---

## Part III — 代償と揺り戻し

### 7. 代償への揺り戻し — native image / Spring AOT / Virtual Threads

- **代償の整理**: (a)起動が重い(暖機+コンテナ構築+リフレクション走査)、(b)実行時に動的すぎる(リフレクション/プロキシ前提)、(c)メモリ footprint。
- **GraalVM native image + Spring AOT**:「典型的なSpring Bootは非常に動的で、構成は実行時に行われる。自動構成は実行時状態への反応に強く依存する」→ native は **closed-world**(classpath はビルド時固定、lazy class loading なし、reflection/proxy/resource は事前に教える必要)。**Spring AOT がビルド時に RuntimeHints を生成**してこの溝を埋める = 「Springが手に入れた動的さを、起動速度のために**意図的に手放す**」逆向きの動き。Spring Boot 4 / Framework 7 / GraalVM 25。
- **Virtual Threads(Project Loom, JEP 444 / JDK 21)**: JVMがスケジュールする軽量スレッド。carrier への mount/unmount。**「プログラミングモデルは変えない」=同期ブロッキングのまま書ける**。pinning(`synchronized`/native内)問題 → JEP 491(JDK 24)で解消。
  - **対比**: Go の goroutine と同型(M:N、ランタイムスケジュール)。Python/Rust/JS の async/await(関数の色問題)とは逆の選択 = Javaは「同期コードのまま並行性をランタイムに渡す」。
- これらは全部 thesis の再確認:制御をランタイムに渡してきたが、その代償(起動・動的さ)を**ランタイム側の進化で取り返しにいっている**。
- 根拠: docs.spring.io/spring-boot/reference/packaging/native-image/introducing-graalvm-native-images.html, docs.spring.io/spring-framework/reference/core/aot.html, openjdk.org/jeps/444, openjdk.org/jeps/491, docs.oracle.com/en/java/javase/21/core/virtual-threads.html, spring.io/projects/release-highlights
- 根拠ファイル: extract_native_aot.json, extract_virtual_threads.json, search_springboot_version.json

### 8. 向く/向かないユースケース

- **向く**: 長時間稼働の業務/エンタープライズ、巨大チーム・長期保守(型・後方互換・成熟エコシステム・規約が効く)、複雑なトランザクション境界や cross-cutting concern(宣言的に織り込める)。
- **不利/過剰**: 起動レイテンシ最優先の FaaS/CLI(JVM暖機+コンテナ構築が重い→native が必要になる)、ごく小さなサービス(Spring は重量級、Go/FastAPI の方が薄い)、極端なメモリ制約環境。
- 切り口は「Javaが遅い/重い」ではなく「**Java/Springが解こうとしている問題と、そのユースケースが解いてほしい問題が違う**」(React記事と同じ締め方)。

### 9. まとめ — 一本の問いに戻る

- thesis再掲。利用者が受け入れている制約を3〜4点に圧縮(JVM暖機モデル/公称型・型消去/コンテナへのライフサイクル委譲/プロキシ由来のself-invocation制約)。
- 「迷ったら "Java/Springはこの制御を誰に渡したか?" に戻る」という判断軸を渡す。

## 参考資料(本文末に再掲予定)

- Java/JVM: openjdk HotSpot Runtime Overview, Oracle JIT Compilation Optimization, JEP 1, Oracle Java SE Support Roadmap, JDK 11 Migration Guide
- 型/例外: dev.java Type Erasure, Oracle Non-Reifiable Types, Autoboxing, Catch or Specify Requirement, JLS ch.11
- Spring core: spring-framework reference — beans introduction / scopes / factory-nature
- Spring AOP: aop introduction-proxies / proxying / pointcuts(self-invocation)
- Spring Boot: auto-configuration / developing-auto-configuration
- 揺り戻し: spring-boot native-image, spring-framework aot, JEP 444, JEP 491, Oracle Virtual Threads(JDK21), spring.io Boot 4.0 / Framework 7.0 GA blog

## 確認したいこと(plan段階)

1. タイトルは仮(リード案)。語感の希望があれば差し替えます。
2. 9セクションはReact記事と同程度の分量。重い場合は Part境界で「Java編/Spring編」に分割も可能(ただし1記事希望と理解しています)。
3. 各セクションの対比相手(Go/Python/Rust/FastAPI/Rails)はこの配分で良いか。Railsは規約の対比で1回だけ登場。
