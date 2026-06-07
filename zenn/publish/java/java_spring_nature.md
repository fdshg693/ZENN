---
title: "JavaとSpringを「制御をランタイム/コンテナに渡す設計」として読む — 他言語経験者のための本質と制約"
emoji: "☕"
type: "tech"
topics: ["java", "spring", "springboot", "jvm", "architecture"]
published: false
---

## この記事について

Go も Python も Rust も TypeScript も書いてきた。型システムも GC も並行モデルも、Web フレームワークの一般論も理解している。**でも Java だけは一度も触っていない** — そういう人に向けた記事です。

文法は一切説明しません。`for` の書き方も `@RestController` の使い方も出てきません。代わりに、

1. なぜ「言語 Java」ではなく「**JVM というプラットフォーム**」として捉えるべきか
2. 公称型・型消去・チェック例外・後方互換は何を保証し、何を強いるのか
3. Spring の DI コンテナは、他言語の DI と何が**本質的に**違うのか
4. アノテーション + プロキシの "magic" はなぜ生じ、どんな制約を**必然的に**生むのか
5. 自動構成(クラスパスから推測)の正体と、予測可能性とのトレードオフ
6. その代償と、native / AOT / Loom という揺り戻しはどう読めるか

を、公式ドキュメントを根拠に整理します。

### 一本の問いで貫く

この記事は次の一文を軸にします。

> **Java/Spring の本質は「制御をランタイムとコンテナに手渡す」こと。**
> まず **JVM** という管理ランタイムにメモリ・実行・移植性の制御を預け、その上で **Spring の DI コンテナ**にアプリの配線とライフサイクルそのものを預ける。代償は「間接性(magic)」と起動の重さ・リフレクション依存であり、近年の native image / Spring AOT / Virtual Threads は、その代償への**揺り戻し**として読める。

以降のセクションは、すべてこの一本の問いの帰結として並んでいます。

:::message
バージョン前提(2026年5月時点)。本文の数値はこの時点のものです。

- **Java: JDK 25 が最新 LTS**(2025年9月 GA)。LTS は 8 / 11 / 17 / 21 / 25 で、次は 29(2027年予定)。6か月ごとのフィーチャーリリース + 隔年 LTS。
- **Spring: Spring Boot 4.0.0(2025年11月 GA)** が現行世代。Spring Framework 7.0 ベースで Java 25 にフォーカス。Spring Boot 3.5 / 3.4 系も保守対象。
:::

---

# Part I — 土台としての Java / JVM

## 1. Java は「言語」ではなく「JVM という管理ランタイムへの約束」

他言語から来ると、つい「Java = 言語仕様」と考えがちですが、Java の本質の半分は **JVM(Java Virtual Machine)** という実行基盤の側にあります。ソースコードは bytecode にコンパイルされ、その bytecode を JVM が実行・最適化・メモリ管理します。「一度書けばどこでも動く」という移植性は、**実行の制御をランタイムに丸ごと渡した対価**として手に入れたものです。

ここで重要なのは、JVM が単なる bytecode インタプリタではなく、**実行しながら賢くなるランタイム**だという点です。HotSpot VM の挙動は明確です。

> HotSpot VM defaults to interpreting Java byte code, and will only JIT compile methods that runtime profiling determines to be "hot" - the methods that have been executed for a threshold number of times.
> ([Oracle / Compilation Optimization](https://docs.oracle.com/javacomponents/jrockit-hotspot/migration-guide/comp-opt.htm))

> 訳: HotSpot VM はデフォルトでは Java バイトコードを**インタプリタ実行**し、実行時プロファイリングが "hot"(閾値回数以上実行された)と判定したメソッドだけを JIT コンパイルする。

これが **tiered compilation** です。Tier 0(インタプリタ)で動かしながらプロファイルを集め、ホットなコードを Tier 4(C2 による高度最適化)まで段階的に引き上げます。しかも JIT 最適化は投機的で、前提が崩れれば deoptimize して下位 Tier に戻れます。

ここから出る性質はひとつです。**Java/JVM は「起動は遅く、暖機(warmup)後に速い」**。プロファイルを集めて最適化するモデルなので、立ち上げ直後はインタプリタ寄りで遅く、しばらく走らせて初めてピーク性能に達します。

これは設計上の賭けです。他言語と対比すると鮮明です。

| | 実行モデル | 起動 | ピーク到達 |
|---|---|---|---|
| **Java/JVM** | bytecode → インタプリタ + JIT | 遅い(暖機が要る) | 実行時プロファイルで賢くなる |
| Go / Rust | AOT でネイティブバイナリ | 即座 | 起動時点でほぼピーク |
| Python | CPython バイトコード + インタプリタ | 速い | JIT は基本なし(実装依存) |

Go や Rust は事前(AOT)にネイティブコードへ落とすので、起動した瞬間がほぼピークです。Java は逆に「実行時に観測して最適化する」方に賭けました。だからこそ **長時間稼働するサーバープロセスに最適化された実行モデル**であり、裏を返せば「すぐ起動してすぐ終わる」用途(CLI や FaaS)とは構造的に相性が悪い。この弱点は Part III で native image として回収されます。

> ここまでの含意: Java を選ぶとは、まず「実行の制御を JVM に渡し、暖機と引き換えに移植性と実行時最適化を得る」という土台を選ぶこと。Spring の話はすべてこの土台の**上**に乗ります。

---

## 2. 型は公称(nominal)で、ジェネリクスは実行時に消える

Java の型システムには、他言語経験者が最初につまずく2つの本質的な性質があります。

### 2.1 公称型(nominal typing)

Java のインタフェース実装は **公称的**です。`implements SomeInterface` と**明示的に名前で宣言しない限り**、たとえメソッドの形が完全に一致していても、その型として扱われません。

これは Go と正反対です。Go のインタフェースは**構造的(structural)**で、必要なメソッドが揃っていれば、宣言なしで暗黙にそのインタフェースを満たします。

```
// Go: メソッドが揃えば暗黙に満たす(implements を書かない)
// Java: implements Comparable を明示しない限り Comparable ではない
```

「ダックタイピング的に振る舞いで繋ぐ」Go/Python の世界から来ると、Java の「名前で明示的に契約を結ぶ」世界は冗長に見えます。が、これは後で出てくる **「インタフェースに対してプログラムせよ」という Spring の作法**の土台でもあります。型の同一性が名前に固定されているからこそ、コンテナは「この型の bean」を一意に指して配線できます。

### 2.2 ジェネリクスは型消去される(type erasure)

これは Java の設計で最も「経験者を驚かせる」一点かもしれません。Java のジェネリクスは**コンパイル時にしか存在しません**。

> Type erasure ensures that no new classes are created for parameterized types; consequently, generics incur no runtime overhead.
> ([dev.java / Type Erasure](https://dev.java/learn/generics/type-erasure))

> 訳: 型消去により、パラメータ化された型に対して新しいクラスは作られない。結果として、ジェネリクスは実行時オーバーヘッドを持たない。

コンパイラは型パラメータを消し、上限境界(なければ `Object`)に置き換えます。その帰結が次です。

> Examples of non-reifiable types are `List<String>` and `List<Number>`; the JVM cannot tell the difference between these types at runtime.
> ([Oracle / Non-Reifiable Types](https://docs.oracle.com/javase/tutorial/java/generics/nonReifiableVarargsType.html))

> 訳: non-reifiable な型の例が `List<String>` と `List<Number>` である。JVM は実行時にこの2つの型を区別できない。

つまり実行時には「ただの `List`」しか存在しません。Rust や C# が monomorphization / reified generics で**実行時にも型情報を保持する**のとは対照的です。Java は後方互換性(後述)のために「型はコンパイラのためのもの、実行時には消す」を選びました。

この「実行時に型情報が薄い」性質は、後で Spring がリフレクションを多用する話と地続きです。**コンパイル時に消えた情報を、実行時にリフレクションで補い直す** — それが Spring の "magic" の一部です(セクション5)。

### 2.3 プリミティブはオブジェクトではない

もう一点。Java は **「すべてがオブジェクト」ではありません**。`int` / `long` / `boolean` などのプリミティブ型はオブジェクトではなく、必要に応じて `Integer` などのラッパーへ自動変換(autoboxing)されます。

Python のように「整数も含めて全部がオブジェクト」という世界から来ると、この「プリミティブとオブジェクトの二層構造」は最初は奇異に映ります。これも性能(プリミティブを箱に入れない)と歴史的経緯のトレードオフであり、Java が「綺麗な統一モデル」より「実用的な妥協」を取る言語であることの一例です。

---

## 3. チェック例外と「壊さない」という約束 — 型と互換性が引き受ける制御

### 3.1 失敗をシグネチャに乗せる、稀な言語

Java は、**失敗の一部を型シグネチャ(`throws`)に書かせ、コンパイラがその処理を強制する**数少ない主流言語です。これが **チェック例外(checked exception)** です。

> The checked exception classes are all exception classes other than the unchecked exception classes. That is, the checked exception classes are `Throwable` and all its subclasses other than `RuntimeException` and its subclasses and `Error` and its subclasses.
> ([JLS / Chapter 11. Exceptions](https://docs.oracle.com/javase/specs/jls/se16/html/jls-11.html))

> 訳: チェック例外クラスとは、アンチェック例外クラス以外のすべての例外クラスである。すなわち `Throwable` とそのサブクラスのうち、`RuntimeException` 系と `Error` 系を除いたもの。

チェック例外は **catch-or-specify 要件**の対象で、呼び出し側は「catch する」か「自分も `throws` で宣言する」かをコンパイラに強制されます。設計指針も公式に明文化されています。

> If a client can reasonably be expected to recover from an exception, make it a checked exception. If a client cannot do anything to recover from the exception, make it an unchecked exception.
> ([Oracle / Unchecked Exceptions — The Controversy](https://docs.oracle.com/javase/tutorial/essential/exceptions/runtime.html))

> 訳: クライアントが回復を期待できるなら checked にし、回復できないなら unchecked にせよ。

他言語のエラーモデルと比べると、Java の立ち位置がはっきりします。

| 言語 | 失敗の表現 | コンパイラの強制 |
|---|---|---|
| **Java** | checked 例外 / unchecked 例外 | checked は catch-or-specify を**強制** |
| Go | `error` を明示的に返す | 戻り値を無視できる(慣習で防ぐ) |
| Rust | `Result<T, E>` + `?` | `#[must_use]` で未処理を警告 |
| Python | 例外(すべて unchecked) | 強制なし |

Java のチェック例外は「失敗を黙って握りつぶせない」という保証を**型レベルで**与えます。Rust の `Result` が思想的に近い一方、Go や Python は「そこは規律で守る」側です。

ただし、これは諸刃です。チェック例外は `throws` がシグネチャに伝播し、ラムダや関数合成と相性が悪く、しばしば冗長になります。だからこそ**実務では多くのフレームワーク(Spring を含む)が、独自例外を `RuntimeException`(unchecked)に倒して checked の連鎖を断ち切っています**。「言語が強制した制約を、フレームワークが部分的に降ろす」という構図は、Java エコシステムを読むうえで覚えておく価値があります。

### 3.2 後方互換性という「宗教」

Java が長期保守と大規模チームで強い最大の理由は、ほとんど宗教的な後方互換性へのコミットです。

> The Java team is committed to backward compatibility. If an application runs in JDK 8, then it will run on JDK 9 and later releases as long as it uses APIs that are supported and intended for external use.
> ([Oracle JDK Migration Guide](https://docs.oracle.com/en/java/javase/11/migrate/index.html))

> 訳: Java チームは後方互換性にコミットしている。JDK 8 で動くアプリケーションは、サポートされ外部利用を意図された API を使う限り、JDK 9 以降でも動く。

この約束は、リリースの仕組みにも支えられています。6か月ごとのフィーチャーリリースに対し、**隔年で LTS(長期サポート)版**を出し(8 / 11 / 17 / 21 / 25、次は 29)、変更は一つひとつ JEP(JDK Enhancement Proposal)として議論されます。さらに Maven Central を中心とした成熟したライブラリ供給網がある。

これが Java の最大の「勝ち筋」です。**「数年前に書いたコードが、新しい JVM でそのまま動き、ライブラリが揃っていて、人を採用できる」** — この予測可能性こそ、エンタープライズや長期プロダクトが Java を選び続ける理由です。新しさより安定を取る、という賭けです。

---

# Part II — 土台の上の Spring(コンテナ)

ここから framework の話です。重要なのは、Spring はあくまで **Part I の JVM という土台の上に乗っている**こと。「実行時に賢いランタイム」「公称型」「リフレクションで補える実行環境」という前提があって初めて成立します。

## 4. Spring の本質 — DI コンテナがオブジェクトの生死を所有する

Spring を「DI ライブラリ」と捉えると本質を外します。より正確には、**Spring はオブジェクトグラフの生成・配線・ライフサイクルを所有する IoC コンテナ**です。Spring が管理するオブジェクトを **bean** と呼びます。

> In Spring, the objects that form the backbone of your application and that are managed by the Spring IoC container are called beans. A bean is an object that is instantiated, assembled, and managed by a Spring IoC container.
> ([Spring / Introduction to the IoC Container](https://docs.spring.io/spring-framework/reference/core/beans/introduction.html))

> 訳: Spring では、アプリケーションの骨格を成し、Spring IoC コンテナによって管理されるオブジェクトを bean と呼ぶ。bean とは、Spring IoC コンテナによって**インスタンス化され、組み立てられ、管理される**オブジェクトである。

「instantiated, assembled, managed」の3語がポイントです。**`new` するのも、依存を注入するのも、生死を管理するのも、あなたではなくコンテナ**です。コンテナの実体は `ApplicationContext`(`BeanFactory` の上位)。

bean の既定スコープは **singleton** で、コンテナは1つのインスタンスをキャッシュして使い回します。

> the Spring IoC container creates exactly one instance of the object defined by that bean definition. This single instance is stored in a cache of such singleton beans, and all subsequent requests and references for that named bean return the cached object.
> ([Spring / Bean Scopes](https://docs.spring.io/spring-framework/reference/core/beans/factory-scopes.html))

> 訳: Spring IoC コンテナは、その bean 定義につき**ちょうど1つ**のインスタンスを生成する。この単一インスタンスはキャッシュに格納され、以降その名前の bean へのすべての要求・参照はキャッシュされたオブジェクトを返す。

さらに `ApplicationContext` は既定で singleton を**起動時に事前生成(eager pre-instantiation)**します。だから「設定ミスや配線エラーは起動時にまとめて爆発する」 — これは後述の起動の重さの一因でもあります。ライフサイクルにも介入でき、初期化コールバック(`@PostConstruct` や `InitializingBean`)はコンテナの singleton 生成ロック内で実行されます。

### 他言語の DI と何が違うのか

DI(依存性注入)というパターン自体は、どの言語にもあります。違うのは **Spring の中央集権性と網羅性**です。

| | DI の形 | コンテナ | スコープ管理 |
|---|---|---|---|
| **Spring** | コンテナが全 bean を所有・配線 | あり(`ApplicationContext`) | singleton / prototype / request / session… |
| FastAPI | `Depends()` による**関数合成** | なし(リクエストごとに解決) | 主にリクエスト単位 |
| Go(wire 等) | **明示的な配線コードを生成/手書き** | なし(コンテナを持たない文化) | 自前 |

FastAPI の `Depends` は「このエンドポイントが必要とする依存を、リクエストのたびに関数として解決する」軽量な仕組みです。Go は「コンテナなんて要らない、依存は明示的に手で配線するのが正義」という文化です。

Spring はそのどちらでもなく、**「アプリ全体のオブジェクトグラフを1つのコンテナが所有し、生死とスコープまで面倒を見る」**方に振り切っています。これは React が「coordinator を中央に置き、複雑性をフレームワーク側が吸収する」と決めたのと同型の賭けです。複雑性をコンテナが引き受ける代わりに、**利用者はコンテナの作法(bean 定義、スコープ、ライフサイクル)に従う**ことを強いられます。

---

## 5. "magic" の正体 — アノテーション + 実行時プロキシ + リフレクション

`@Transactional` を付けるだけでトランザクションが張られ、`@Cacheable` を付けるだけでキャッシュが効く。この "magic" の正体を、他言語経験者は誤解しがちです。**これはコンパイル時のマクロでもコード生成でもありません。実行時にプロキシを挟む**仕組みです。

> Spring AOP defaults to using standard JDK dynamic proxies for AOP proxies. This enables any interface (or set of interfaces) to be proxied. Spring AOP can also use CGLIB proxies. This is necessary to proxy classes rather than interfaces.
> ([Spring / AOP Proxies](https://docs.spring.io/spring-framework/reference/core/aop/introduction-proxies.html))

> 訳: Spring AOP は既定で標準の JDK 動的プロキシを使う。これによりインタフェース(の集合)をプロキシ化できる。Spring AOP は CGLIB プロキシも使える。これはインタフェースではなく**クラス**をプロキシ化するために必要である。

仕組みはこうです。

> If the target object to be proxied implements at least one interface, a JDK dynamic proxy is used... If the target object does not implement any interfaces, a CGLIB proxy is created which is a runtime-generated subclass of the target type.
> ([Spring / Proxying Mechanisms](https://docs.spring.io/spring-framework/reference/core/aop/proxying.html))

> 訳: プロキシ対象がインタフェースを1つ以上実装していれば JDK 動的プロキシが使われる。インタフェースを実装していなければ、**実行時生成されたサブクラス**である CGLIB プロキシが作られる。

つまり Spring は、あなたの bean を直接呼ばせず、**間に「見た目が同じプロキシ」を差し込み**、その中で「本来のメソッド呼び出しの前後にトランザクション開始/コミットなどを織り込む(weaving)」のです。weaving は実行時に行われます。

### 原理から制約が導かれる

ここが本セクションの山場です。「プロキシで実現している」という**実装の事実**から、いくつかの制約が**必然的に**導かれます。最も有名なのが **self-invocation(自己呼び出し)問題**です。

> Due to the proxy-based nature of Spring's AOP framework, calls within the target object are, by definition, not intercepted. For JDK proxies, only public interface method calls on the proxy can be intercepted.
> ([Spring / Declaring a Pointcut](https://docs.spring.io/spring-framework/reference/core/aop/ataspectj/pointcuts.html))

> 訳: Spring AOP がプロキシベースである性質上、**対象オブジェクト内部からの呼び出しは、定義上インターセプトされない**。JDK プロキシでは、プロキシ上の public なインタフェースメソッド呼び出しのみがインターセプトされる。

具体的には、`@Transactional` の付いたメソッドを、**同じクラスの別メソッドから直接呼ぶとトランザクションが効きません**。なぜなら内部呼び出しはプロキシを経由せず、`this`(本体)を直接叩いているからです。Spring を始めた人が必ず一度は踏む地雷ですが、原理(プロキシは外側に被さるだけ)から見れば当然の帰結です。

同じ原理から、他の制約も出ます。

- **`final` メソッド/クラスは advise できない**(CGLIB はサブクラス化で動くため、オーバーライドできないものは織り込めない)
- 原則として **public メソッド経由**で呼ぶ前提
- デバッグ時にスタックトレースが深く、プロキシのクラス名が挟まる

### 他言語の「メタプログラミング」との違い

この "magic" は、他言語の同種の仕組みとは層が違います。

| | 仕組み | いつ効く |
|---|---|---|
| **Spring(@Transactional 等)** | 実行時プロキシ + リフレクション | **実行時**(起動時にプロキシ生成) |
| Rust の `#[derive]` / マクロ | コンパイル時に展開 | コンパイル時 |
| Go の go:generate | コード生成 | ビルド前 |
| Python のデコレータ | 関数オブジェクトのラップ | 定義時(直接的) |

Rust のマクロや Go のコード生成は、**コンパイル/ビルド時**に全部が確定し、生成結果が静的に見えます。Python のデコレータは関数を直接ラップするので、`self.method()` でも普通に効きます。

Spring が選んだのは **実行時メタプログラミング**です。リフレクションでアノテーションを走査し、プロキシを動的に生成して織り込む。この柔軟さ(再コンパイルなしに横断的関心事を差し込める)の対価が、**静的解析しづらさ・起動時のコスト・self-invocation のような非自明な制約**です。そして「実行時に動的にやる」という性質は、次の自動構成でさらに加速し、Part III の native image と正面衝突します。

---

## 6. 規約と自動構成 — クラスパスから状態を「推測」する

Spring Boot が「何も書かなくても Web サーバーが立ち上がる」のはなぜか。答えは身も蓋もないほど直接的です。

> `@EnableAutoConfiguration` tells Spring Boot to "guess" how you want to configure Spring, based on the jar dependencies that you have added. Since `spring-boot-starter-web` added Tomcat and Spring MVC, the auto-configuration assumes that you are developing a web application and sets up Spring accordingly.
> ([Spring Boot Reference](https://docs.spring.io/spring-boot/reference/using/auto-configuration.html))

> 訳: `@EnableAutoConfiguration` は、追加された jar 依存に基づいて、あなたがどう構成したいかを Spring Boot に**「推測(guess)」させる**。`spring-boot-starter-web` が Tomcat と Spring MVC を追加したので、自動構成は「Web アプリを作っているのだろう」と仮定して Spring をセットアップする。

つまり **クラスパスに何の jar があるか**が、暗黙の構成入力になっています。この「推測」は条件付き bean で実装されています。

> Classes that implement auto-configuration are annotated with `@AutoConfiguration`... Usually, auto-configuration classes use `@ConditionalOnClass` and `@ConditionalOnMissingBean` annotations. This ensures that auto-configuration applies only when relevant classes are found and when you have not declared your own `@Configuration`.
> ([Spring Boot / Creating Your Own Auto-configuration](https://docs.spring.io/spring-boot/reference/features/developing-auto-configuration.html))

> 訳: 自動構成クラスは `@AutoConfiguration` が付く。…通常は `@ConditionalOnClass` と `@ConditionalOnMissingBean` を使い、関連クラスが見つかり、かつ**あなたが自分の `@Configuration` を宣言していないとき**だけ適用されるようにする。

この `@ConditionalOnMissingBean` が効いて、自動構成は **non-invasive(押しつけがましくない)** になります。

> Auto-configuration is non-invasive. At any point, you can start to define your own configuration to replace specific parts of the auto-configuration. For example, if you add your own `DataSource` bean, the default embedded database support backs away.
> ([Spring Boot Reference](https://docs.spring.io/spring-boot/reference/using/auto-configuration.html))

> 訳: 自動構成は non-invasive である。いつでも自分の構成を定義して特定部分を置き換えられる。例えば自前の `DataSource` bean を足せば、既定の組み込み DB サポートは**引っ込む**。

### 規約の系譜と、予測可能性とのトレードオフ

「設定より規約(convention over configuration)」という発想自体は Rails が広めたもので、Spring Boot はその系譜にあります。一方、Go や FastAPI は「明示的に書く」志向が強い。

- **Spring Boot**: クラスパスと既存 bean の有無から構成を**推測**。最速で立ち上がるが、構成が暗黙になる。
- **Go / FastAPI**: 何をどう繋ぐかを基本的に**明示**。立ち上げの手数は増えるが、挙動がコードから直接読める。

トレードオフは明快です。**起動の速さ・ボイラープレートの少なさ**と引き換えに、**「いま何がなぜ効いているか」が暗黙化**します。Spring Boot はこの代償を自覚していて、`--debug` で起動すると「どの条件が成立し、どの自動構成が効いた/効かなかったか」のレポートを出す機能を用意しています。**「暗黙だが、問い合わせれば説明できる」**という設計です。

そしてもう一点。「実行時にクラスパスの状態を見て構成を推測する」という設計は、極めて**動的**です。この動的さが、次の native image の世界と真っ向からぶつかります。

---

# Part III — 代償と揺り戻し

## 7. 代償への揺り戻し — native image / Spring AOT / Virtual Threads

ここまでで Java/Spring が「制御をランタイムとコンテナに渡す」ことで得たものと、その代償が見えてきました。代償を3つに整理します。

1. **起動が重い** — JVM の暖機 + コンテナの bean 事前生成 + リフレクションによるクラスパス走査
2. **実行時に動的すぎる** — リフレクションとプロキシが前提。何が起きるかが実行時まで確定しない
3. **メモリ footprint** — JVM 本体 + 大量のメタデータ

面白いのは、ここ数年の Java/Spring の主要な動きが、**この代償をランタイム側の進化で取り返しにいく「揺り戻し」**として読めることです。

### 7.1 GraalVM native image + Spring AOT — 動的さを意図的に手放す

GraalVM native image は、Java アプリを**事前にネイティブ実行ファイルへ落とす**技術です。

> Native Images generally have a smaller memory footprint and start faster than their JVM counterparts.
> ([Spring Boot / GraalVM Native Images](https://docs.spring.io/spring-boot/reference/packaging/native-image/index.html))

> 訳: ネイティブイメージは一般に、JVM 版より**メモリ使用量が小さく、起動が速い**。

まさに代償 1・3 への直接の回答です。しかし、ここで Part II の動的さが牙を剥きます。Spring 公式自身が矛盾を率直に認めています。

> Typical Spring Boot applications are quite dynamic and configuration is performed at runtime. In fact, the concept of Spring Boot auto-configuration depends heavily on reacting to the state of the runtime in order to configure things correctly.
> ([Spring Boot / Introducing GraalVM Native Images](https://docs.spring.io/spring-boot/reference/packaging/native-image/introducing-graalvm-native-images.html))

> 訳: 典型的な Spring Boot アプリは非常に動的で、構成は実行時に行われる。実際、Spring Boot 自動構成という概念は、正しく構成するために**実行時の状態に反応すること**に強く依存している。

ところが native image は **closed-world(閉じた世界)** を要求します。

> The application classpath is fixed at build time and cannot change. There is no lazy class loading, everything shipped in the executables will be loaded in memory on startup.
> ([Spring Boot / Introducing GraalVM Native Images](https://docs.spring.io/spring-boot/reference/packaging/native-image/introducing-graalvm-native-images.html))

> 訳: アプリケーションのクラスパスは**ビルド時に固定**され、変更できない。遅延クラスロードはなく、実行ファイルに入るものはすべて起動時にメモリへロードされる。

しかも GraalVM は、リフレクション・リソース・シリアライズ・動的プロキシといった動的要素を自動では把握できず、**事前に教えてもらう必要があります**。そこで登場するのが **Spring AOT(Ahead-of-Time)処理**です。Spring はビルド時にアプリを解析し、`RuntimeHints`(リフレクションやプロキシの使用箇所のヒント)を生成して、この溝を埋めます。

構図としてはこうです。**Spring は「実行時に動的に推測する」力で開発体験を得たのに、起動速度のためにその動的さをビルド時に解析して "畳み込み"、半ば手放しにいっている。** これは thesis の部分的な撤回 — 「ランタイムに渡した制御の一部を、ビルド時に取り戻す」動きです。Spring Boot 4 / Spring Framework 7 では GraalVM 25 を前提に、この path がさらに整備されています。

### 7.2 Virtual Threads(Project Loom) — 同期コードのまま並行性をランタイムに渡す

代償ではなく「制御をランタイムに渡す」思想の**正統な進化**として読めるのが Virtual Threads です。JDK 21 で標準化されました(JEP 444)。

> Introduce virtual threads to the Java Platform. Virtual threads are lightweight threads that dramatically reduce the effort of writing, maintaining, and observing high-throughput concurrent applications.
> ([JEP 444: Virtual Threads](https://openjdk.org/jeps/444))

> 訳: 仮想スレッドを Java プラットフォームに導入する。仮想スレッドは軽量スレッドであり、高スループットな並行アプリの記述・保守・観測の労力を劇的に減らす。

仕組みは Go の goroutine とほぼ同型です。仮想スレッドは OS ではなく **JVM がスケジュールする**ユーザモードスレッドで、少数の OS スレッド(carrier)の上に多数の仮想スレッドを mount / unmount します(M:N)。ブロッキング I/O で待つときは carrier から外れ、その間 carrier は別の仮想スレッドを走らせます。

決定的なのは、**プログラミングモデルを変えないこと**です。Project Loom の発表資料は端的にこう述べています。

> No change to the programming model, it's the one we already know.
> ([Alan Bateman / The challenges of introducing Virtual Threads, JVMLS 2023](https://cr.openjdk.org/~alanb/jvmls2023/loom-jvmls2023.pdf))

> 訳: プログラミングモデルに変更はない。すでに知っているモデルのままだ。

ここが各言語の並行モデルの分岐点です。

| | 並行モデル | コードの色 |
|---|---|---|
| **Java(Virtual Threads)** | M:N、JVM がスケジュール | **同期ブロッキングのまま**書ける |
| Go(goroutine) | M:N、ランタイムがスケジュール | 同期のまま書ける(同型) |
| Python / Rust / JS(async/await) | イベントループ + async | **関数に "色"** がつく(async 汚染) |

Python・Rust・JS が選んだ async/await は、いわゆる「関数の色問題(colored functions)」を持ち込みます。async な関数は async な文脈からしか呼べず、コードベースが二色に染まる。Java は Go と同じく**「同期コードのまま書き、並行性のスケジューリングはランタイムに渡す」**側を選びました。これはまさに本記事の thesis(制御をランタイムに渡す)の最も新しく、最も綺麗な実例です。

ただし制約もあります。仮想スレッドが carrier から外れられない **pinning** という現象です。

> There are two scenarios in which a virtual thread cannot be unmounted during blocking operations because it is pinned to its carrier: When it executes code inside a `synchronized` block or method, or When it executes a `native` method or a foreign function.
> ([JEP 444: Virtual Threads](https://openjdk.org/jeps/444))

> 訳: 仮想スレッドが carrier に **pin** され、ブロッキング操作中に unmount できないシナリオが2つある。`synchronized` ブロック/メソッド内のコードを実行しているとき、または `native` メソッド/外部関数を実行しているとき。

JEP 444 の時点では、頻繁に pin する `synchronized` を `ReentrantLock` に書き換える、という回避策が推奨されていました。この pinning 自体も後に JDK 24(JEP 491「Synchronize Virtual Threads without Pinning」)で大きく解消されています。「制約を見つけてランタイム側で潰す」という、Java らしい漸進の仕方です。

---

## 8. Java/Spring が向くユースケース、向かないユースケース

ここまでの性質から、向き不向きは素直に出ます。

**Java/Spring が勝ちやすい領域**

- **長期保守・大規模チームの業務/エンタープライズ系**。後方互換の約束・公称型の明示性・成熟したエコシステム・自動構成の規約が、人の入れ替わりと長い寿命に効く。
- **複雑なトランザクション境界や横断的関心事(認証・監査・キャッシュ)を持つアプリ**。宣言的に(プロキシで)織り込めることの価値が、間接性のコストを上回る。
- **長時間稼働するサーバープロセス**。JVM の暖機コストを、稼働時間で十分に償却できる。

**Java/Spring が不利、またはコストが過剰な領域**

- **起動レイテンシが最優先の FaaS / CLI**。JVM の暖機 + コンテナ構築が重く、毎回起動するモデルと噛み合わない。native image が要るが、それは Part II の動的さを手放す追加コストを意味する。
- **ごく小さなサービスや薄い API**。Spring の中央集権コンテナは重量級で、Go や FastAPI の方が薄く速く立ち上がる。
- **極端にメモリ制約の厳しい環境**。JVM 本体 + メタデータの footprint が予算を超えることがある。

ここで取るべき視点は、React を語るときと同じです。**「Java は遅い/重い」ではなく、「Java/Spring が解こうとしている問題と、そのユースケースが解いてほしい問題が違う」**。Java/Spring は「長く・大きく・複雑なものを、予測可能に運用する」問題に賭けた道具です。

---

## 9. まとめ — 一本の問いに戻る

Java と Spring は、**「制御をランタイムとコンテナに手渡す」**という一貫した賭けの上に立っています。

- **JVM** に実行・最適化・メモリの制御を渡し、暖機と引き換えに移植性と実行時最適化を得た。
- **Spring のコンテナ**にオブジェクトの生成・配線・ライフサイクルを渡し、間接性と引き換えに横断的関心事の宣言的な扱いと爆速の立ち上げを得た。

その賭けと引き換えに、利用者は少なくとも次の制約を受け入れています。

1. **JVM の暖機モデル** — 起動は遅く、温まって速い(FaaS/CLI とは構造的に相性が悪い)
2. **公称型と型消去** — 型はコンパイラのためのもの、実行時には薄い(だからリフレクションで補う)
3. **コンテナへのライフサイクル委譲** — `new` も生死もコンテナが所有し、その作法に従う
4. **プロキシ由来の非自明な制約** — self-invocation で `@Transactional` が効かない、等は実装の必然

そして native image / Spring AOT / Virtual Threads は、この賭けの代償を**ランタイム側の進化で取り返す揺り戻し**として一貫して読めます。

他言語から Java/Spring に入るとき、個々の "magic" や制約に面食らったら、**「いま、どの制御を誰に渡しているのか?」**に立ち返ってください。`@Transactional` が効かないのも、起動が遅いのも、クラスパスから構成が生えてくるのも、すべて同じ一本の問いの帰結として見えるはずです。

---

## 参考資料

### Java / JVM
- [HotSpot Runtime Overview — OpenJDK](https://openjdk.org/groups/hotspot/docs/RuntimeOverview.html)
- [Compilation Optimization (HotSpot JIT) — Oracle](https://docs.oracle.com/javacomponents/jrockit-hotspot/migration-guide/comp-opt.htm)
- [JEP 1: JDK Enhancement-Proposal & Roadmap Process](https://openjdk.org/jeps/1)
- [Oracle Java SE Support Roadmap](https://www.oracle.com/java/technologies/java-se-support-roadmap.html)
- [Oracle JDK Migration Guide(後方互換)](https://docs.oracle.com/en/java/javase/11/migrate/index.html)

### 型・例外
- [Type Erasure — Dev.java](https://dev.java/learn/generics/type-erasure)
- [Non-Reifiable Types — Oracle](https://docs.oracle.com/javase/tutorial/java/generics/nonReifiableVarargsType.html)
- [Autoboxing and Unboxing — Oracle](https://docs.oracle.com/javase/tutorial/java/data/autoboxing.html)
- [The Catch or Specify Requirement — Oracle](https://docs.oracle.com/javase/tutorial/essential/exceptions/catchOrDeclare.html)
- [Unchecked Exceptions — The Controversy — Oracle](https://docs.oracle.com/javase/tutorial/essential/exceptions/runtime.html)
- [JLS Chapter 11. Exceptions](https://docs.oracle.com/javase/specs/jls/se16/html/jls-11.html)

### Spring(コア)
- [Introduction to the Spring IoC Container and Beans](https://docs.spring.io/spring-framework/reference/core/beans/introduction.html)
- [Bean Scopes](https://docs.spring.io/spring-framework/reference/core/beans/factory-scopes.html)
- [Customizing the Nature of a Bean](https://docs.spring.io/spring-framework/reference/core/beans/factory-nature.html)

### Spring(AOP / プロキシ)
- [AOP Proxies](https://docs.spring.io/spring-framework/reference/core/aop/introduction-proxies.html)
- [Proxying Mechanisms](https://docs.spring.io/spring-framework/reference/core/aop/proxying.html)
- [Declaring a Pointcut(self-invocation)](https://docs.spring.io/spring-framework/reference/core/aop/ataspectj/pointcuts.html)

### Spring Boot(自動構成 / native)
- [Auto-configuration](https://docs.spring.io/spring-boot/reference/using/auto-configuration.html)
- [Creating Your Own Auto-configuration](https://docs.spring.io/spring-boot/reference/features/developing-auto-configuration.html)
- [Introducing GraalVM Native Images](https://docs.spring.io/spring-boot/reference/packaging/native-image/introducing-graalvm-native-images.html)
- [Ahead of Time Optimizations — Spring Framework](https://docs.spring.io/spring-framework/reference/core/aot.html)

### Virtual Threads / リリース
- [JEP 444: Virtual Threads](https://openjdk.org/jeps/444)
- [JEP 491: Synchronize Virtual Threads without Pinning](https://openjdk.org/jeps/491)
- [Virtual Threads — Oracle(JDK 21)](https://docs.oracle.com/en/java/javase/21/core/virtual-threads.html)
- [Spring Framework 7.0 General Availability](https://spring.io/blog/2025/11/13/spring-framework-7-0-general-availability)
- [Spring Boot 4.0.0 available now](https://spring.io/blog/2025/11/20/spring-boot-4-0-0-available-now)
