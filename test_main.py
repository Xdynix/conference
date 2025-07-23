from pytest_mock import MockFixture

import main as sut


def test(mocker: MockFixture) -> None:
    mock_print = mocker.patch.object(sut, "print")
    sut.main()
    mock_print.assert_called_once()
