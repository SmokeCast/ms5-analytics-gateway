import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import main


class AnalyticsGatewayTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'ATHENA_ENABLED': 'true', 'ATHENA_OUTPUT_S3': 's3://smokecast-query-results/',
            'ATHENA_DATABASE': 'smokecast_analytics', 'AWS_REGION': 'us-east-1',
        }, clear=False)
        self.env.start()
        self.athena = MagicMock()
        self.athena.start_query_execution.return_value = {'QueryExecutionId': 'query-123'}
        self.athena.get_query_execution.return_value = {'QueryExecution': {'Status': {'State': 'SUCCEEDED'}}}
        self.athena.get_query_results.return_value = {'ResultSet': {
            'ResultSetMetadata': {'ColumnInfo': [{'Name': 'country'}, {'Name': 'detections'}]},
            'Rows': [{'Data': [{'VarCharValue': 'country'}, {'VarCharValue': 'detections'}]},
                     {'Data': [{'VarCharValue': 'Perú'}, {'VarCharValue': '42'}]}]},
            'NextToken': 'next-1'}
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.env.stop()

    @patch('main.client')
    def test_reports_query_status_and_results(self, factory):
        factory.return_value = self.athena
        reports = self.client.get('/api/analytics/reports')
        self.assertEqual(reports.status_code, 200)
        self.assertEqual(len(reports.json()['reports']), 4)
        response = self.client.post('/api/analytics/queries', json={'report': 'fire_summary', 'country': 'Perú'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['query_id'], 'query-123')
        self.assertIn("Perú", self.athena.start_query_execution.call_args.kwargs['QueryString'])
        self.assertEqual(self.client.get('/api/analytics/queries/query-123').json()['status'], 'SUCCEEDED')
        result = self.client.get('/api/analytics/queries/query-123/results?max_results=10')
        self.assertEqual(result.json()['rows'], [{'country': 'Perú', 'detections': '42'}])

    def test_disabled_mode_is_explicit(self):
        with patch.dict(os.environ, {'ATHENA_ENABLED': 'false', 'ATHENA_OUTPUT_S3': ''}, clear=False):
            self.assertFalse(self.client.get('/api/analytics/status').json()['athena_enabled'])
            self.assertEqual(self.client.post('/api/analytics/queries', json={'report': 'fire_summary'}).status_code, 503)

    def test_rejects_unknown_reports_and_query_ids(self):
        self.assertEqual(self.client.post('/api/analytics/queries', json={'report': 'drop_database'}).status_code, 404)
        self.assertEqual(self.client.get('/api/analytics/queries/../../secret').status_code, 404)


if __name__ == '__main__':
    unittest.main()
