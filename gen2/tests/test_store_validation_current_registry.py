"""Raw current-revision INSERT guard under the declared trigger catalog."""
from gen2.tests import test_validation_current_registry as current
from gen2.tests import test_store_extraction_validations_v2 as raw
from gen2.tests import router_fixtures as rf


class DDLCurrentRegistryTest(current.CurrentCases, rf.RecordCase):
    RAW = True
    setUp, send = raw.DDLV2Test.setUp, raw.DDLV2Test.send
