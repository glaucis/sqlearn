"""
Show the installed version
==========================

Import sqlearn and print the version it was installed as, which hatch-vcs
read from the git tag the package was built from.
"""

import sqlearn

print(sqlearn.__version__)
