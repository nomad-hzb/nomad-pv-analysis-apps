import logging
from datetime import datetime

from openpyxl import Workbook
from sheet_data_entry_guide import add_guide_sheet
from sheet_experiment import add_experiment_sheet
from sheet_how_to_cite import add_citation_sheet

logger = logging.getLogger(__name__)


class ExperimentExcelBuilder:
    def __init__(self, process_sequence, is_testing=False, samples=None):
        self.process_sequence = process_sequence
        self.is_testing = is_testing
        self.samples = samples  # {header: value} rows to prefill, see add_experiment_sheet
        self.workbook = Workbook()

    def build_excel(self):
        add_experiment_sheet(
            self.workbook, self.process_sequence, self.is_testing, samples=self.samples
        )
        add_guide_sheet(self.workbook)
        add_citation_sheet(self.workbook)

    def save(self, filename=None):
        if filename is None:
            current_date = datetime.now().strftime("%Y%m%d")
            filename = f"{current_date}_experiment_file.xlsx"
        self.workbook.save(filename)
        logger.info("File saved as: %s", filename)
