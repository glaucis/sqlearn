"""The release part of sqlearn's version, apart from the selection."""


def release(version: str) -> str:
    """Return the release part of a version: ``0.1`` of ``0.1.dev5+g….d2026``.

    sqlearn's version comes from git and changes with every commit (its dev,
    local and date parts); its release part changes only with a release.

    Parameters
    ----------
    version : str
        A version as setuptools-scm gives it.

    Returns
    -------
    str
        The version up to ``.dev`` or ``+``.
    """
    return version.split(".dev")[0].split("+")[0]
