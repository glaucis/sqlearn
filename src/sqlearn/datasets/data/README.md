# The bundled datasets

Three small datasets ship with sqlearn as CSV files beside this page, so
`sq.datasets.iris()`, `wine()` and `breast_cancer()` work offline. They are
copies of the files scikit-learn 1.9.1 distributes (its `load_iris`,
`load_wine` and `load_breast_cancer`), rewritten with a header row of column
names and the class code in a final `target` column. The values are
unchanged.

All three come from the UCI Machine Learning Repository
(<https://archive.ics.uci.edu>), which licenses them under the Creative
Commons Attribution 4.0 International licence (CC BY 4.0,
<https://creativecommons.org/licenses/by/4.0/>). You may share and adapt
them, including commercially, if you credit the creators and cite the source
as below and say that they have been changed (here: reformatted as CSV with a
header). scikit-learn redistributes them under its BSD licence.

## iris.csv

- **Source:** Iris, UCI Machine Learning Repository,
  <https://archive.ics.uci.edu/dataset/53/iris>. 150 rows, 4 features, 3
  classes. The copy is scikit-learn's, which follows Fisher's paper and so
  corrects two data points that the UCI file gets wrong.
- **Creator:** R.A. Fisher. **Donor:** Michael Marshall. July 1988.
- **Citation:** Fisher, R.A. "The use of multiple measurements in taxonomic
  problems", Annual Eugenics, 7, Part II, 179-188 (1936); also in
  "Contributions to Mathematical Statistics" (John Wiley, NY, 1950).

## wine.csv

- **Source:** Wine, UCI Machine Learning Repository,
  <https://archive.ics.uci.edu/dataset/109/wine>. 178 rows, 13 features, 3
  classes.
- **Creators:** M. Forina et al., PARVUS - An Extendable Package of Programs
  for Data Exploration, Classification and Correlation. Institute of
  Pharmaceutical and Food Analysis and Technologies, Via Brigata Salerno,
  16147 Genoa, Italy.
- **Citation:** Aeberhard, S., Coomans, D. and de Vel, O. Comparison of
  Classifiers in High Dimensional Settings, Tech. Rep. no. 92-02 (1992),
  Dept. of Computer Science and Dept. of Mathematics and Statistics, James
  Cook University of North Queensland.

## breast_cancer.csv

- **Source:** Breast Cancer Wisconsin (Diagnostic), UCI Machine Learning
  Repository, <https://archive.ics.uci.edu/dataset/17>. 569 rows, 30
  features, 2 classes (212 malignant coded 0, 357 benign coded 1).
- **Creators:** Dr. William H. Wolberg, W. Nick Street, Olvi L. Mangasarian.
  **Donor:** Nick Street. November 1995.
- **Citation:** W.N. Street, W.H. Wolberg and O.L. Mangasarian. Nuclear
  feature extraction for breast tumor diagnosis. IS&T/SPIE 1993 International
  Symposium on Electronic Imaging: Science and Technology, volume 1905, pages
  861-870, San Jose, CA, 1993.
