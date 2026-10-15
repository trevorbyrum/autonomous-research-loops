"""Raw current-revision INSERT guard under normal and reversed trigger order."""
from gen2.tests import test_validation_current_registry as current
from gen2.tests import test_extraction_records as records, test_store_extraction_validations_v2 as raw


class DDLCurrentRegistryTest(current.CurrentCases, records.RecordCase):
    setUp, send = raw.DDLV2Test.setUp, raw.DDLV2Test.send
