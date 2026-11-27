---
type: note
tags: [datasets, licensing, attribution, iris, wine, breast-cancer]
summary: "Describes the three bundled CSV datasets (iris, wine, breast cancer), their UCI sources, CC BY 4.0 licence, and required citations."
related: ["https://archive.ics.uci.edu/dataset/53/iris", "https://archive.ics.uci.edu/dataset/109/wine", "https://archive.ics.uci.edu/dataset/17/breast+cancer+wisconsin+diagnostic", "https://creativecommons.org/licenses/by/4.0/"]
mdindex: [type=edb465, tags=233b39, summary=0a5df8, related=31343b]
---
# The bundled datasets

Three small datasets ship with sqlearn as CSV files beside this page, so
`sq.datasets.iris()`, `wine()` and `breast_cancer()` work offline. They are
copies of the files scikit-learn 1.9.1 distributes (its `load_iris`,
`load_wine` and `load_breast_cancer`), rewritten with a header row of column
names and the class code in a final `target` column. The values are
unchanged.

All three come from the UCI Machine Learning Repository
(<https://archive.ics.uci.edu>), which licenses them under the Creative Commons
Attribution 4.0 International licence (CC BY 4.0,
<https://creativecommons.org/licenses/by/4.0/>). You may share and adapt them,
including commercially, if you credit the creators and cite the source as below
(UCI's own dataset citation, with its DOI, heads each entry) and say that they
have been changed (here: reformatted as CSV with a header). scikit-learn
redistributes them under its BSD licence.

## iris.csv

- **Source:** Iris, UCI Machine Learning Repository,
  <https://archive.ics.uci.edu/dataset/53/iris>. Donated 30 June 1988; UCI
  names no donor. 150 rows, 4 features, 3 classes.
- **UCI's dataset citation:** Fisher, R. (1936). Iris [Dataset]. UCI Machine
  Learning Repository. <https://doi.org/10.24432/C56C76>.
- **As described by scikit-learn 1.9.1:** the copy is scikit-learn's, which
  follows Fisher's paper and so corrects two data points that the UCI file
  gets wrong. Creator R.A. Fisher; donor Michael Marshall, July 1988.
  Fisher, R.A. "The use of multiple measurements in taxonomic problems",
  Annual Eugenics, 7, Part II, 179-188 (1936); also in "Contributions to
  Mathematical Statistics" (John Wiley, NY, 1950).

## wine.csv

- **Source:** Wine, UCI Machine Learning Repository,
  <https://archive.ics.uci.edu/dataset/109/wine>. Donated 30 June 1991.
  178 rows, 13 features, 3 classes.
- **Creators (UCI):** Stefan Aeberhard and M. Forina.
- **UCI's dataset citation:** Aeberhard, S. and Forina, M. (1992). Wine
  [Dataset]. UCI Machine Learning Repository.
  <https://doi.org/10.24432/C5PC7J>.
- **UCI's introductory paper:** Aeberhard, S., Coomans, D. and de Vel, O.
  Pattern Recognition, 1994.
- **As described by scikit-learn 1.9.1:** creators M. Forina et al., PARVUS -
  An Extendable Package of Programs for Data Exploration, Classification and
  Correlation. Institute of Pharmaceutical and Food Analysis and
  Technologies, Via Brigata Salerno, 16147 Genoa, Italy. Citation:
  Aeberhard, S., Coomans, D. and de Vel, O. Comparison of Classifiers in High
  Dimensional Settings, Tech. Rep. no. 92-02 (1992), Dept. of Computer
  Science and Dept. of Mathematics and Statistics, James Cook University of
  North Queensland.

## breast_cancer.csv

- **Source:** Breast Cancer Wisconsin (Diagnostic), UCI Machine Learning
  Repository,
  <https://archive.ics.uci.edu/dataset/17/breast+cancer+wisconsin+diagnostic>.
  Donated 31 October 1995. 569 rows, 30 features, 2 classes (212 malignant
  coded 0, 357 benign coded 1).
- **UCI's dataset citation:** Wolberg, W., Mangasarian, O., Street, N. and
  Street, W. (1993). Breast Cancer Wisconsin (Diagnostic) [Dataset]. UCI
  Machine Learning Repository. <https://doi.org/10.24432/C5DW2B>.
- **As described by scikit-learn 1.9.1:** creators Dr. William H. Wolberg, W.
  Nick Street, Olvi L. Mangasarian; donor Nick Street, November 1995. W.N.
  Street, W.H. Wolberg and O.L. Mangasarian. Nuclear feature extraction for
  breast tumor diagnosis. IS&T/SPIE 1993 International Symposium on
  Electronic Imaging: Science and Technology, volume 1905, pages 861-870, San
  Jose, CA, 1993.
