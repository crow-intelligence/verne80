import verne80


def test_the_package_imports_and_reports_a_version():
    assert isinstance(verne80.__version__, str)
    assert len(verne80.__version__.split(".")) >= 3


def test_the_public_api_is_reachable():
    for name in verne80.__all__:
        assert hasattr(verne80, name), name


def test_the_book_is_wired_up():
    assert verne80.BOOK.expected_chapters == 37
