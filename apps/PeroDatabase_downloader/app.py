"""Application assembly.

Authenticates against the configured NOMAD server, wires the token into a
DataManager, and hands both the manager and the auth result to the GUI.
This is the single import the notebook needs. To retarget the app (for
example to Dash), swap the GUI class here and leave the rest untouched.
"""

import config
from auth import authenticate
from data_manager import DataManager
from gui_components import ExtractorGUI


class NomadExtractorApp:
    def __init__(self, api_url=config.NOMAD_API_URL):
        self.auth = authenticate(api_url)
        self.data_manager = DataManager(api_url=api_url, token=self.auth.token)
        self.gui = ExtractorGUI(self.data_manager, auth=self.auth)

    def launch(self):
        return self.gui.render()
