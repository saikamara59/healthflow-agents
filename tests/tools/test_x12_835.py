import pytest

from healthflow_agents.tools.x12_835 import parse_835


def test_x12_835_is_a_documented_stub():
    with pytest.raises(NotImplementedError, match="remittance_parser"):
        parse_835("ISA*00*...~")
