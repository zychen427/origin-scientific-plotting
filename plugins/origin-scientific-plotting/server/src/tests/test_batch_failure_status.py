import json
import unittest
from unittest.mock import patch

from origin_pro_mcp.tools import batch_workflows, research_workflows


class BatchFailureStatusTests(unittest.TestCase):
    def test_graph_batch_stops_and_reports_partial_failure(self):
        tasks = [dict(graph_name='G1', data_book='B', data_sheet='S', x_col=1, y_col=2),
                 dict(graph_name='G2', data_book='B', data_sheet='S', x_col=1, y_col=2)]
        with patch.object(batch_workflows, 'create_graph', side_effect=RuntimeError('failed after creation')) as create:
            result = json.loads(batch_workflows.batch_create_graphs(tasks))
        self.assertEqual(result['status'], 'partial_failure')
        self.assertEqual(result['results'][0]['error_type'], 'RuntimeError')
        self.assertEqual(create.call_count, 1)

    def test_fit_batch_stops_and_reports_error_type(self):
        tasks = [dict(data_book='B', data_sheet='S', x_col=1, y_col=2)] * 2
        with patch.object(research_workflows, 'curve_fit', side_effect=ValueError('bad input')) as fit:
            result = json.loads(research_workflows.batch_curve_fit(tasks))
        self.assertEqual(result['status'], 'partial_failure')
        self.assertEqual(result['results'][0]['error_type'], 'ValueError')
        self.assertEqual(fit.call_count, 1)


if __name__ == '__main__': unittest.main()
