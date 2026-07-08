import json
import tornado.testing
from visdom.server.app import Application

class TestWorkspaceAPI(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return Application()

    def test_get_workspaces(self):
        response = self.fetch('/api/v1/workspaces')
        self.assertEqual(response.code, 200)
        data = json.loads(response.body)
        self.assertTrue(isinstance(data, list))
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['id'], 'ws_1')

    def test_create_workspace(self):
        response = self.fetch('/api/v1/workspaces', method='POST', body=json.dumps({
            "name": "Test Workspace",
            "description": "My test workspace"
        }))
        self.assertEqual(response.code, 201)
        data = json.loads(response.body)
        self.assertEqual(data['id'], 'ws_new')
        self.assertEqual(data['name'], 'Test Workspace')

    def test_get_workspace(self):
        response = self.fetch('/api/v1/workspaces/ws_1')
        self.assertEqual(response.code, 200)
        data = json.loads(response.body)
        self.assertEqual(data['id'], 'ws_1')

    def test_update_workspace(self):
        response = self.fetch('/api/v1/workspaces/ws_1', method='PUT', body=json.dumps({
            "name": "Updated Name"
        }))
        self.assertEqual(response.code, 200)
        data = json.loads(response.body)
        self.assertEqual(data['name'], 'Updated Name')

    def test_delete_workspace(self):
        response = self.fetch('/api/v1/workspaces/ws_1', method='DELETE')
        self.assertEqual(response.code, 204)

    def test_share_workspace(self):
        response = self.fetch('/api/v1/workspaces/ws_1/share', method='POST', body='')
        self.assertEqual(response.code, 201)
        data = json.loads(response.body)
        self.assertEqual(data['workspace_id'], 'ws_1')
        self.assertIn('url_token', data)
