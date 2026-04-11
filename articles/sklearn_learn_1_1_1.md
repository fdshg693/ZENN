---
title: "scikit-learnのLinearRegressionを実装まで追う: Ordinary Least Squares入門"
emoji: "📈"
type: "tech"
topics:
  - python
  - scikitlearn
  - machinelearning
  - numpy
  - statistics
published: true
---

scikit-learn の `LinearRegression` は「最小二乗法で線形回帰を行う」という説明で済ませられがちですが、実際にコードを読むと、データの前処理、ソルバの分岐、予測時の多出力対応まで、かなり丁寧に組まれています。

この記事では次の 2 本立てで整理します。

- 本編: `LinearRegression` を最短コードと Diabetes データセットで動かす
- 深掘り編: scikit-learn の内部実装を、実際のソースパスと簡略化したコード断片で追う

## ソースコードの探し方

scikit-learn の実装は GitHub 上で公開されています。この記事では、ソースコードへの参照をすべて [scikit-learn/scikit-learn](https://github.com/scikit-learn/scikit-learn) のリポジトリ (main ブランチ) 起点で統一します。

以降のコード断片は、説明に関係ある部分だけを GitHub 上の実装から抜き出して簡略化したものです。実際の分岐やバリデーションはもう少し多いので、気になったら元のソースも合わせて読むのがおすすめです。

## そもそも線形回帰で何をやっているのか

コードに入る前に、線形回帰 (Linear Regression) が結局のところ何をやっているのかを整理しておきます。この節を押さえておくと、あとで `fit` や `predict` を読むときに「ここで何を計算しているのか」が一気に見えやすくなります。

### モデル: 「入力と出力はだいたい直線的な関係」だと仮定する

線形回帰は、入力 $x$ から出力 $y$ を予測するために、**入力と出力のあいだに直線的な (=線形の) 関係があると仮定する** モデルです。

特徴量が 1 個だけのときは、中学校で習った 1 次関数と同じ形になります。

$$
\hat{y} = w x + b
$$

- $w$: 傾き。特徴量の重み (weight)、係数 (coefficient) とも呼ぶ
- $b$: 切片 (intercept)。$x = 0$ のときの予測値
- $\hat{y}$: モデルが出す「予測値」。真の値 $y$ と区別するためにハット記号を付ける

特徴量が複数 (たとえば $p$ 個) あるときも、発想は同じで、各特徴量に重みをかけて足すだけです。

$$
\hat{y} = w_1 x_1 + w_2 x_2 + \dots + w_p x_p + b
$$

これを行列・ベクトルでまとめ直すと、冒頭にも出てきた

$$
\hat{y} = X w + b
$$

になります。$X$ は「行 = サンプル、列 = 特徴量」の行列、$w$ は長さ $p$ の係数ベクトルです。

「線形回帰モデルを作る」というのは、具体的にはこの式の中の $w$ と $b$ を **データから決める** ことを意味します。式の形 ($\hat{y} = Xw + b$) は人間が先に決めてしまっていて、自由に動くパラメータは $w$ と $b$ だけです。

### 学習: 「誤差が一番小さくなる直線」を探す

次は「$w$ と $b$ をどう決めるか」です。線形回帰では、**学習データの上で予測値 $\hat{y}_i$ と実測値 $y_i$ のずれがなるべく小さくなる** ような直線を選びます。このずれ $y_i - \hat{y}_i$ を残差 (residual) と呼びます。

ただし、残差をそのまま足すと正負が打ち消し合ってしまうので、**残差を二乗してから合計** したもの (残差平方和, RSS) を「悪さ」の尺度として使います。

$$
\mathcal{L}(w, b) = \sum_{i=1}^{n} (y_i - \hat{y}_i)^2 = \sum_{i=1}^{n} \left(y_i - (x_i^T w + b)\right)^2
$$

この $\mathcal{L}$ を最小にする $(w, b)$ を求める問題が、いわゆる **Ordinary Least Squares (OLS, 通常の最小二乗法)** です。二乗するのは主に次の理由です。

- 符号を消して「ずれの大きさ」だけ見たい (絶対値でもよいが、数学的に扱いにくい)
- 2 乗関数は滑らかで微分可能なので、閉じた形 (正規方程式) で解が求まる
- 大きなずれを強く罰したい

直感的には「散らばった点の真ん中を貫くように、一番フィットする直線を 1 本引く」操作に近いです。scikit-learn の `fit` メソッドを呼ぶと、内部でこの最小化問題を解いて、最適な $w$ と $b$ を計算して `coef_` と `intercept_` に格納してくれます。

具体的な解き方としては、教科書でよく見る正規方程式

$$
\hat{w} = (X^T X)^{-1} X^T y
$$

があります。ただし実務のコードでは、逆行列をそのまま作るより数値的に安定な `lstsq` 系のルーチンを使うのが普通で、scikit-learn もそうしています (これは後半の内部実装編で見ます)。

### 予測: 学習した直線に入力を代入するだけ

$w$ と $b$ さえ決まってしまえば、予測はただの代入です。新しい入力 $X_\text{test}$ を、学習済みの式に入れます。

$$
\hat{y}_\text{test} = X_\text{test} w + b
$$

scikit-learn ではこれが `predict` メソッドに対応します。つまり `predict` 自体は「新しいデータに学習結果を当てはめる」以上のことは何もしていません。学習時の重い計算はすべて `fit` の中で終わっています。

### 評価: テストデータで「どれだけ当たっているか」を数値化する

直線を引けても、それが実際に「使える直線」かは別問題です。学習に使ったデータ上で点とのずれが小さいのは当たり前なので、**学習に使わなかったデータ (テストデータ) に対して予測させ、真の値と比べる** ことで、本当に未知のデータに効くかを測ります。

この記事では 2 つの指標を使います。

- **MSE (Mean Squared Error, 平均二乗誤差)**: 残差の二乗を平均したもの。0 に近いほど良い。単位は「目的変数の 2 乗」なので、値そのものの直感的な解釈はしづらいが、モデル間の相対比較や学習時の損失関数としてはよく使う。
- **$R^2$ (Coefficient of Determination, 決定係数)**: 「平均値を返すだけの雑なモデル」と比べてどれだけ残差を減らせたかを表す指標。1 に近いほど良く、0 なら「平均値モデルと同程度」、負になると「平均値モデルより悪い」。

まとめると、線形回帰で「何をやっているのか」はこの 4 ステップです。

1. **モデルを仮定**: $\hat{y} = Xw + b$ という線形の関係を仮定する
2. **学習 (`fit`)**: 学習データ上で残差平方和 $\sum (y_i - \hat{y}_i)^2$ を最小にする $w, b$ を求める
3. **予測 (`predict`)**: 求めた $w, b$ を新しい入力に代入して $\hat{y}$ を計算する
4. **評価 (`mean_squared_error`, `r2_score`)**: テストデータでどれだけ当たっているかを数値化する

この流れを頭に置いたうえで、実際に scikit-learn のコードに落としていきます。

## まずは最短の例

この節で動かすのは、scikit-learn 公式ユーザーガイドの [Linear Models · Ordinary Least Squares](https://scikit-learn.org/stable/modules/linear_model.html#ordinary-least-squares) に載っている最短のサンプルコードそのものです。変数名など細かい差はありますが、呼び出している API と入力データは公式と同じです。出力の見え方を揃えるために、`print` の代わりに `icecream.ic` を使っています。

最初に import だけまとめて書いておきます。以降のコード例では、同じ import を省略します。

```python
from icecream import ic

from sklearn.datasets import load_diabetes
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
```

公式の最短例に揃えたコードはこうです。

```python
regressor = LinearRegression()
regressor.fit([[0, 0], [1, 1], [2, 2]], [0, 1, 2])

ic(regressor.coef_)
ic(regressor.intercept_)
```

出力例:

```python
ic| regressor.coef_: array([0.5, 0.5])
ic| regressor.intercept_: np.float64(1.1102230246251565e-16)
```

ここで見ているのは次の 2 つだけです。

- `coef_`: 回帰係数 $w$
- `intercept_`: 切片 $b$

予測式は $\hat{y} = Xw + b$ です。scikit-learn は、この係数と切片を `fit` で学習し、`predict` で使います。

今回の結果は `coef_ = [0.5, 0.5]`、`intercept_ ≈ 0` なので、学習された式は

$$
\hat{y} = 0.5 \, x_1 + 0.5 \, x_2
$$

です。学習データ $(0, 0) \to 0$, $(1, 1) \to 1$, $(2, 2) \to 2$ をこの式に代入するとちょうど一致するので、3 点すべてをぴったり通る「当たり前の直線」が求まっていることが分かります。ちなみに切片の値 `1.11e-16` は浮動小数点演算の誤差で、実質 0 です。

「学習した」というのは、まさにこの $w = (0.5, 0.5)$ と $b = 0$ を残差平方和を最小化することで見つけてきた、ということです。

関連語句:

- Ordinary Least Squares, OLS: 残差平方和を最小化する最も基本的な線形回帰
- residual: 実測値 $y$ と予測値 $\hat{y}$ の差
- intercept: 入力が 0 のときの予測値に相当する定数項

## Diabetes データセットで学習から評価まで動かす

次は少し実践寄りの例です。こちらも、scikit-learn 公式の Example ギャラリーに載っている [Ordinary Least Squares and Ridge Regression](https://scikit-learn.org/stable/auto_examples/linear_model/plot_ols_ridge.html#sphx-glr-auto-examples-linear-model-plot-ols-ridge-py) のうち OLS (通常の最小二乗法) 部分のコードをそのまま使っています。可視化のコード (matplotlib 部分) は省き、学習と評価の流れだけに絞っているのが違いです。使っているデータは scikit-learn に同梱されている Diabetes データセットです。

```python
X, y = load_diabetes(return_X_y=True)
X = X[:, [2]]

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=20,
    shuffle=False,
)

regressor = LinearRegression().fit(X_train, y_train)
y_pred = regressor.predict(X_test)

ic(regressor.coef_)
ic(regressor.intercept_)
ic(f"Mean squared error: {mean_squared_error(y_test, y_pred):.2f}")
ic(f"Coefficient of determination: {r2_score(y_test, y_pred):.2f}")
```

実行例は次のとおりです。

```python
ic| regressor.coef_: array([938.23786125])
ic| regressor.intercept_: np.float64(152.91886182616113)
ic| f"Mean squared error: {mean_squared_error(y_test, y_pred):.2f}": 'Mean squared error: 2548.07'
ic| f"Coefficient of determination: {r2_score(y_test, y_pred):.2f}": 'Coefficient of determination: 0.47'
```

このコードでやっていることを順に言うと:

1. `load_diabetes(return_X_y=True)` で特徴量行列 `X` と目的変数 `y` を受け取る
2. `X[:, [2]]` で 3 列目、つまり BMI に対応する 1 特徴量だけを使う
3. `train_test_split(..., test_size=20, shuffle=False)` で末尾 20 件をテスト用に分ける
4. `LinearRegression().fit(X_train, y_train)` で学習する
5. `predict` で予測し、`mean_squared_error` と `r2_score` で評価する

この例では `shuffle=False` にしているので、ランダム分割ではなく「先頭 422 件が学習、末尾 20 件がテスト」です。時系列データを厳密に扱う例ではありませんが、分割ロジックを追いやすい設定です。

ここでのデータの意味も押さえておくと、

- **特徴量 $x$**: BMI (体格指数) をスケーリングしたもの (1 列だけ使用)
- **目的変数 $y$**: 1 年後の糖尿病進行度を表す数値 (およそ 25〜346 の範囲)

なので「ある患者の BMI から、1 年後の進行度を予測する」という問題を、線形回帰 1 本で解こうとしている、という状況です。学習データとテストデータに分けているのは、**学習に使っていないデータでの性能こそが本当に知りたいもの** だからです。学習データ上で誤差が小さいのは当たり前 (その誤差を小さくするように係数を決めているので)、新しいデータで当たるかどうかが勝負になります。

### 学習された直線を読む

出力の `coef_` と `intercept_` を「そもそも何をやっているのか」の節で立てた式に当てはめると、学習された予測式はこうなります。

$$
\hat{y} = 938.24 \, x_\text{BMI} + 152.92
$$

この式からは、次のことが読み取れます。

- $x_\text{BMI} = 0$ のとき (スケーリング後の BMI が平均的な患者)、予測される進行度は切片の `152.92`
- $x_\text{BMI}$ が 1 単位増えると、予測される進行度が `938.24` だけ上がる

つまり、**「BMI が大きいほど 1 年後の進行度も大きい」という正の相関を、1 本の直線で要約した** わけです。実際の `fit` の内部では、学習データ 422 件の上で残差平方和 $\sum (y_i - \hat{y}_i)^2$ を最小化して、この傾きと切片を求めています。

### 評価の数値を読む

次にテストデータ 20 件に対して `predict` を走らせた結果を、`MSE` と $R^2$ で見ています。

- **MSE ≈ 2548**: テスト 20 件での残差 $y_i - \hat{y}_i$ の二乗の平均値。平方根を取ると $\sqrt{2548} \approx 50.5$ なので、「1 件あたりだいたい進行度スケールで $\pm 50$ 前後ずれている」という感覚値になります ($y$ は 25〜346 のレンジ)。
- **$R^2 \approx 0.47$**: テストデータの分散のうち、モデルが説明できた割合。`1 - (残差平方和 / テストデータの分散 × n)` で求まる値で、「何もせず平均値を返すだけのモデル」に比べて残差平方和を 47% 減らせた、という意味になります。1 に近いほど良く、0 なら「平均値モデルと同程度」、負になれば「平均値モデルより悪い」。

要するに、BMI 1 特徴量だけで糖尿病の進行度を予測するモデルとしては「まぁそこそこ当たっている (けど精度は高くない)」くらいの結果、と読み取れます。精度を上げるには、残りの 9 特徴量も使う、非線形モデルに変える、正則化を入れる、などの方向があります。

関連語句:

- feature: 入力変数。ここでは 10 個あるうち 1 列だけ使っている
- target: 予測したい値。ここでは糖尿病の進行度
- hold-out: 学習用と評価用にデータを一度だけ分ける方法
- MSE: 残差の二乗の平均。大きな誤差を強く罰する
- R^2: 平均予測よりどれだけ良いかを見る指標

## ここから内部実装を読む

ここからは、実際の scikit-learn のソースを追います。サンプルを動かす話と、内部で何が起きるかを分けて読みたい人は、この節から読み始めても大丈夫です。

以下では、参照先をすべて GitHub 上の scikit-learn リポジトリで統一します。

### 1. `load_diabetes` はどこからデータを持ってくるのか

ソース:

- [sklearn/datasets/_base.py](https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/datasets/_base.py)

`load_diabetes` の本体は次のような流れです。

```python
def load_diabetes(*, return_X_y=False, as_frame=False, scaled=True):
    data_filename = "diabetes_data_raw.csv.gz"
    target_filename = "diabetes_target.csv.gz"

    data = load_gzip_compressed_csv_data(data_filename)
    target = load_gzip_compressed_csv_data(target_filename)

    if scaled:
        data = scale(data, copy=False)
        data /= data.shape[0] ** 0.5

    if return_X_y:
        return data, target

    return Bunch(...)
```

さらに、その中で呼ばれている `load_gzip_compressed_csv_data` はこうです。

```python
def load_gzip_compressed_csv_data(data_file_name, *, data_module=DATA_MODULE, **kwargs):
    data_path = resources.files(data_module) / data_file_name
    with data_path.open("rb") as compressed_file:
        compressed_file = gzip.open(compressed_file, mode="rt", encoding="utf-8")
        data = np.loadtxt(compressed_file, **kwargs)
    return data
```

ポイントは 3 つです。

- データは外からダウンロードしているのではなく、パッケージ内リソースとして同梱されている
- `importlib.resources` 経由でファイルパスを取っているので、配布形式が変わっても扱いやすい
- `scaled=True` が既定なので、読み込んだ直後に特徴量がスケーリングされる

関連語句:

- `Bunch`: dict ライクに属性アクセスできる scikit-learn 独自コンテナ
- `importlib.resources`: パッケージ内ファイルを安全に読むための標準ライブラリ
- scaling: 特徴量のスケールをそろえる前処理

### 2. `train_test_split` はデータ本体ではなくインデックスを動かす

ソース:

- [sklearn/model_selection/_split.py](https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/model_selection/_split.py)
- [sklearn/utils/validation.py](https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/utils/validation.py)

まず `train_test_split` の芯になる部分です。

```python
def train_test_split(*arrays, test_size=None, train_size=None, random_state=None,
                     shuffle=True, stratify=None):
    arrays = indexable(*arrays)
    n_samples = _num_samples(arrays[0])
    n_train, n_test = _validate_shuffle_split(...)

    if shuffle is False:
        train = np.arange(n_train)
        test = np.arange(n_train, n_train + n_test)
    else:
        CVClass = StratifiedShuffleSplit if stratify is not None else ShuffleSplit
        cv = CVClass(test_size=n_test, train_size=n_train, random_state=random_state)
        train, test = next(cv.split(X=arrays[0], y=stratify))

    return list(
        chain.from_iterable(
            (_safe_indexing(a, train), _safe_indexing(a, test)) for a in arrays
        )
    )
```

入り口の `indexable` も重要です。

```python
def indexable(*iterables):
    result = [_make_indexable(X) for X in iterables]
    check_consistent_length(*result)
    return result
```

つまり `train_test_split` は、最初に「全部インデックスで切れる形に直す」「長さが一致しているか確認する」を済ませてから、整数インデックスだけを分割しています。

この設計の利点は明確です。

- `X` と `y` の対応関係を崩しにくい
- 疎行列や DataFrame でも同じ発想で扱える
- データ本体を直接シャッフルしないので、ロジックが単純になる

この例では `shuffle=False` なので、実際には `ShuffleSplit` を使わず、`np.arange` で前半と後半のインデックスを切っています。

関連語句:

- indexable: 添字アクセスできる形にそろえる前処理
- stratify: ラベル比率を保ちながら分割する方法
- safe indexing: ndarray, pandas, 疎行列などの差を吸収して切り出す処理

### 3. `LinearRegression.fit` は前処理してからソルバを分岐する

ソース:

- [sklearn/linear_model/_base.py](https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/linear_model/_base.py)

`LinearRegression.fit` の流れを簡略化すると、次のようになります。

```python
def fit(self, X, y, sample_weight=None):
    X, y = validate_data(...)

    X, y, X_offset, y_offset, _, sample_weight_sqrt = _preprocess_data(
        X,
        y,
        fit_intercept=self.fit_intercept,
        copy=copy_X_in_preprocess_data,
        sample_weight=sample_weight,
    )

    if self.positive:
        self.coef_ = optimize.nnls(X, y)[0]
    elif sp.issparse(X):
        self.coef_ = lsqr(X_centered, y, atol=self.tol, btol=self.tol)[0]
    else:
        self.coef_, _, self.rank_, self.singular_ = linalg.lstsq(X, y, cond=cond)
        self.coef_ = self.coef_.T

    if y.ndim == 1:
        self.coef_ = np.ravel(self.coef_)

    self._set_intercept(X_offset, y_offset)
    return self
```

見るべき点は 4 つあります。

#### `_preprocess_data` が中心化を担当する

同じ [sklearn/linear_model/_base.py](https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/linear_model/_base.py) 内の `_preprocess_data` では、`fit_intercept=True` のときに `X` と `y` の平均を取り、中心化を行います。

```python
def _preprocess_data(X, y, *, fit_intercept, sample_weight=None, ...):
    if fit_intercept:
        if X_is_sparse:
            X_offset, X_var = mean_variance_axis(X, axis=0, weights=sample_weight)
        else:
            X_offset = _average(X, axis=0, weights=sample_weight, xp=xp)
            X -= X_offset

        y_offset = _average(y, axis=0, weights=sample_weight, xp=xp)
        y -= y_offset
```

この中心化により、係数の推定と切片の計算を分離しやすくなります。実装としても、まず中心化済みデータで係数を求め、そのあとで切片を戻す形になっています。

#### 入力の条件でソルバが分かれる

- `positive=True`: `scipy.optimize.nnls`
- 疎行列: `scipy.sparse.linalg.lsqr`
- それ以外の通常ケース: `scipy.linalg.lstsq`

「線形回帰 = 常に同じ計算」ではなく、入力条件に応じて解き方を切り替えているのが分かります。

特に通常ケースで `linalg.lstsq` を使っているのは重要で、明示的に $(X^T X)^{-1} X^T y$ を作るより、数値計算上ずっと安定です。

#### `np.ravel` は単一ターゲット用の形直し

`y.ndim == 1` のときだけ `self.coef_ = np.ravel(self.coef_)` を行っています。これは係数を `(n_features,)` の 1 次元配列にそろえるためです。

#### 切片は `_set_intercept` で戻す

```python
def _set_intercept(self, X_offset, y_offset, X_scale=None):
    if self.fit_intercept:
        if self.coef_.ndim == 1:
            self.intercept_ = y_offset - X_offset @ self.coef_
        else:
            self.intercept_ = y_offset - X_offset @ self.coef_.T
    else:
        self.intercept_ = 0.0
```

つまり切片は、前処理で覚えておいた平均 `X_offset`, `y_offset` と、学習済み係数から復元しています。

関連語句:

- centering: 平均を引いて 0 周りにそろえること
- least squares solver: 最小二乗問題を解く数値計算ルーチン
- rank deficiency: 特徴量どうしの独立性が弱く、解が不安定になる状態
- non-negative least squares: 係数を非負に制約する最小二乗

### 4. `predict` は係数の次元で単一出力と多出力を切り替える

同じ [sklearn/linear_model/_base.py](https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/linear_model/_base.py) にある `predict` 周辺はかなり読みやすいです。

```python
def _decision_function(self, X):
    X = validate_data(self, X, accept_sparse=["csr", "csc", "coo"], reset=False)
    coef_ = self.coef_
    if coef_.ndim == 1:
        return X @ coef_ + self.intercept_
    else:
        return X @ coef_.T + self.intercept_

def predict(self, X):
    return self._decision_function(X)
```

ここでの分岐は「サンプル数が 1 件かどうか」ではなく、「1 サンプルあたりの出力変数が 1 個か複数個か」です。

- 単一ターゲット: `coef_.shape == (n_features,)`
- マルチターゲット: `coef_.shape == (n_targets, n_features)`

そのため、多出力のときは `coef_.T` が必要になります。

`@` 演算子を使っているのもポイントで、数式の $Xw + b$ と対応が取りやすく、密行列でも疎行列でも同じ見た目で書けます。

関連語句:

- single-target regression: 出力が 1 変数の回帰
- multi-target regression: 出力が複数変数の回帰
- matrix multiplication: 行列積

### 5. `mean_squared_error` と `r2_score` は何を計算しているのか

ソース:

- [sklearn/metrics/_regression.py](https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/metrics/_regression.py)

まず `mean_squared_error` の核心はかなり素直です。

```python
output_errors = _average(
    (y_true - y_pred) ** 2,
    axis=0,
    weights=sample_weight,
    xp=xp,
)
```

式で書けば、単一ターゲットなら

$$
\mathrm{MSE} = \frac{1}{n} \sum_{i=1}^{n} (y_i - \hat{y}_i)^2
$$

です。`sample_weight` があれば、単純平均ではなく重み付き平均になります。

次に `r2_score` は、残差平方和と全変動を比べています。

```python
numerator = xp.sum(weight * (y_true - y_pred) ** 2, axis=0)
denominator = xp.sum(
    weight * (y_true - _average(y_true, axis=0, weights=sample_weight, xp=xp)) ** 2,
    axis=0,
)

return _assemble_r2_explained_variance(...)
```

最終的な計算の芯は `_assemble_r2_explained_variance` にあり、標準形はこうです。

```python
output_scores = 1 - (numerator / denominator)
```

つまり

$$
R^2 = 1 - \frac{\sum_i (y_i - \hat{y}_i)^2}{\sum_i (y_i - \bar{y})^2}
$$

です。平均値だけを返す雑なモデルより良ければ 0 より大きくなり、かなり悪ければ負にもなります。

関連語句:

- residual sum of squares, RSS: 残差平方和
- total sum of squares, TSS: 平均からのばらつきの総和
- explained variance: 予測がどれだけ分散を説明しているかを見る近縁概念

## 深掘り編: ここからは理論を強める

ここから先はサンプルを動かすのに必須ではありませんが、`LinearRegression` を「使える」から「読める」に進めるために重要です。

### OLS は何を最小化しているのか

切片込みの線形回帰は、次の残差平方和を最小化します。

$$
(\hat{w}, \hat{b}) = \arg\min_{w, b} \sum_{i=1}^{n} \left(y_i - (x_i^T w + b)\right)^2
$$

行列形式にすると、切片の扱いを吸収したうえで

$$
\hat{w} = \arg\min_w \lVert y - Xw \rVert_2^2
$$

です。

教科書では正規方程式

$$
\hat{w} = (X^T X)^{-1} X^T y
$$

がよく出てきますが、実務コードでは逆行列をあからさまに作らず、`lstsq` のような数値的に安定したルーチンを使うのが普通です。scikit-learn の実装もその流れに沿っています。

### 線形回帰の係数をどう解釈すべきか

係数は「他の条件が同じなら、特徴量が 1 単位増えたとき予測値がどれだけ変わるか」を表します。ただし、それを素直に解釈してよいかは別問題です。

注意点は少なくとも次のとおりです。

- 特徴量どうしが強く相関していると、係数は不安定になる
- 外れ値に弱い
- 線形性や等分散性などの仮定が大きく崩れると、推定や解釈が危うくなる
- 予測性能が欲しいだけなら、係数の解釈可能性と性能は必ずしも一致しない

関連語句:

- multicollinearity: 説明変数どうしの強い相関
- heteroscedasticity: 誤差分散が一定でない状態
- outlier: 外れ値
- inference vs prediction: 係数の解釈が目的か、予測性能が目的かの違い

### R^2 だけで評価しないほうがいい理由

`R^2` は便利ですが、万能ではありません。

- 負になることがある
- 外れ値の影響を受ける
- 予測誤差のスケール感そのものは分からない
- データリークがあると簡単に高く見える

そのため、回帰では少なくとも `MSE` や `RMSE`、必要に応じて `MAE` も合わせて見るのが普通です。さらに、残差プロットや交差検証も欲しくなります。

### なぜ Ridge や Lasso も合わせて学ぶべきか

OLS は基本ですが、特徴量が増えると過学習や多重共線性に弱い場面が出ます。そのときに次の正則化付き回帰が出てきます。

- Ridge: 係数の二乗和に罰則を入れる
- Lasso: 係数の絶対値和に罰則を入れる

scikit-learn の線形モデルを読むなら、`LinearRegression` の次は `Ridge` と `Lasso` に進むと理解がつながります。

## 参考資料

公式ドキュメントと、信頼してたどりやすい教科書・資料を中心に挙げます。

### scikit-learn 公式

- [Linear Models · Ordinary Least Squares](https://scikit-learn.org/stable/modules/linear_model.html#ordinary-least-squares) (この記事の「まずは最短の例」の出典)
- [Ordinary Least Squares and Ridge Regression](https://scikit-learn.org/stable/auto_examples/linear_model/plot_ols_ridge.html#sphx-glr-auto-examples-linear-model-plot-ols-ridge-py) (「Diabetes データセットで学習から評価まで動かす」の出典)
- [Model evaluation · Regression metrics](https://scikit-learn.org/stable/modules/model_evaluation.html#regression-metrics)
- [Diabetes dataset](https://scikit-learn.org/stable/datasets/toy_dataset.html#diabetes-dataset)

### 統計・機械学習の理論

- [NIST/SEMATECH e-Handbook of Statistical Methods](https://www.itl.nist.gov/div898/handbook/)
- [An Introduction to Statistical Learning](https://www.statlearning.com/) (Chapter 3: Linear Regression)
- [The Elements of Statistical Learning](https://hastie.su.domains/ElemStatLearn/) (Chapter 3: Linear Methods for Regression)
- [Penn State STAT 501, Regression Methods](https://online.stat.psu.edu/stat501/)

## まとめ

`LinearRegression` の表面 API は小さいですが、内部では次の流れがきれいに分離されています。

- データ読み込み: `load_diabetes` が同梱データを読み、必要ならスケールする
- 分割: `train_test_split` がインデックスベースで安全に train/test を作る
- 学習: `fit` が前処理してから入力条件に応じたソルバを選ぶ
- 予測: `predict` が係数の次元を見て単一出力と多出力を分ける
- 評価: `mean_squared_error` と `r2_score` が残差ベースで性能を数値化する

「とりあえず使う」段階を超えてライブラリの中身まで読めるようになると、ハイパーパラメータや前処理の意味も一気に腹落ちしやすくなります。