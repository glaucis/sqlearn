"""A module that records its own import, so a test can tell it was never run."""

import sys

vars(sys)["modules"]["sqlearn_test_imported"] = True


class X:
    """A class a test names in a file but must never import."""
