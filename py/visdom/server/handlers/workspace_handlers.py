import json
import tornado.web
from visdom.server.handlers.base_handlers import BaseHandler

class WorkspacesHandler(BaseHandler):
    def get(self):
        """GET /api/v1/workspaces - Return list of workspaces (mock)"""
        workspaces = [
            {"id": "ws_1", "name": "Default Workspace", "description": "The default workspace"},
            {"id": "ws_2", "name": "Team A", "description": "Workspace for Team A"}
        ]
        self.write(json.dumps(workspaces))
        self.set_header("Content-Type", "application/json")
        self.set_status(200)

    def post(self):
        """POST /api/v1/workspaces - Create a workspace (mock)"""
        data = tornado.escape.json_decode(self.request.body) if self.request.body else {}
        name = data.get("name", "New Workspace")
        description = data.get("description", "")
        
        workspace = {
            "id": "ws_new",
            "name": name,
            "description": description
        }
        self.write(json.dumps(workspace))
        self.set_header("Content-Type", "application/json")
        self.set_status(201)

class WorkspaceDetailHandler(BaseHandler):
    def get(self, workspace_id):
        """GET /api/v1/workspaces/{id} - Get workspace details (mock)"""
        workspace = {
            "id": workspace_id,
            "name": f"Workspace {workspace_id}",
            "description": "Mocked workspace description"
        }
        self.write(json.dumps(workspace))
        self.set_header("Content-Type", "application/json")
        self.set_status(200)

    def put(self, workspace_id):
        """PUT /api/v1/workspaces/{id} - Update workspace (mock)"""
        data = tornado.escape.json_decode(self.request.body) if self.request.body else {}
        workspace = {
            "id": workspace_id,
            "name": data.get("name", f"Updated Workspace {workspace_id}"),
            "description": data.get("description", "Updated description")
        }
        self.write(json.dumps(workspace))
        self.set_header("Content-Type", "application/json")
        self.set_status(200)

    def delete(self, workspace_id):
        """DELETE /api/v1/workspaces/{id} - Delete workspace (mock)"""
        self.set_status(204)

class WorkspaceShareHandler(BaseHandler):
    def post(self, workspace_id):
        """POST /api/v1/workspaces/{id}/share - Generate share link (mock)"""
        share_info = {
            "workspace_id": workspace_id,
            "url_token": "share_token_12345",
            "expires_at": None,
            "share_url": f"/workspace/{workspace_id}?token=share_token_12345"
        }
        self.write(json.dumps(share_info))
        self.set_header("Content-Type", "application/json")
        self.set_status(201)
