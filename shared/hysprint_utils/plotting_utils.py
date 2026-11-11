import ipywidgets as widgets
from IPython.display import Markdown, display

# LAYOUT lives in ui_constants; still importable from here.
from hysprint_utils.ui_constants import LAYOUT


# --- Widget Factory Functions ---
class WidgetFactory:
    @staticmethod
    def create_button(description, button_style="", tooltip="", icon="", min_width=True):
        """Create a button with standard styling"""
        layout = (
            widgets.Layout(min_width=LAYOUT["BUTTON_MIN_WIDTH"])
            if min_width
            else widgets.Layout(width="auto")
        )
        return widgets.Button(
            description=description,
            button_style=button_style,
            tooltip=tooltip,
            icon=icon,
            layout=layout,
        )

    @staticmethod
    def create_dropdown(options, description="", width="standard", value=None):
        """Create a dropdown with standard styling"""
        width_map = {
            "standard": LAYOUT["DROPDOWN_WIDTH"],
            "wide": LAYOUT["DROPDOWN_WIDE"],
            "extra_wide": LAYOUT["DROPDOWN_EXTRA_WIDE"],
            "label": LAYOUT["LABEL_WIDTH"],
        }
        dropdown = widgets.Dropdown(
            options=options,
            description=description,
            layout=widgets.Layout(width=width_map.get(width, LAYOUT["DROPDOWN_WIDTH"])),
        )
        if value is not None:
            dropdown.value = value
        return dropdown

    @staticmethod
    def create_text_input(placeholder="", description="", width="standard", password=False):
        """Create a text input with standard styling"""
        width_map = {"standard": LAYOUT["TEXT_INPUT_WIDTH"], "wide": LAYOUT["TOKEN_INPUT_WIDTH"]}
        widget_class = widgets.Password if password else widgets.Text
        return widget_class(
            placeholder=placeholder,
            description=description,
            style={"description_width": "initial"},
            layout=widgets.Layout(width=width_map.get(width, LAYOUT["TEXT_INPUT_WIDTH"])),
        )

    @staticmethod
    def create_output(min_height="standard", scrollable=False, border=True):
        """Create an output widget with standard styling"""
        height_map = {
            "standard": LAYOUT["OUTPUT_MIN_HEIGHT"],
            "medium": LAYOUT["OUTPUT_MEDIUM_HEIGHT"],
            "large": LAYOUT["OUTPUT_LARGE_HEIGHT"],
        }

        layout_props = {"min_height": height_map.get(min_height, LAYOUT["OUTPUT_MIN_HEIGHT"])}

        if scrollable:
            layout_props.update(
                {
                    "width": LAYOUT["OUTPUT_SCROLL_WIDTH"],
                    "height": LAYOUT["OUTPUT_SCROLL_HEIGHT"],
                    "overflow": "scroll",
                }
            )

        if border:
            layout_props.update(
                {
                    "border": LAYOUT["BORDER_LIGHT"],
                    "padding": LAYOUT["PADDING_STANDARD"],
                    "margin": LAYOUT["MARGIN_STANDARD"] + " 0 0 0",
                }
            )

        return widgets.Output(layout=layout_props)

    @staticmethod
    def create_radio_buttons(options, description="", value=None, width="standard"):
        """Create radio buttons with standard styling"""
        width_map = {"standard": LAYOUT["DROPDOWN_WIDTH"], "wide": LAYOUT["DROPDOWN_WIDE"]}
        radio = widgets.RadioButtons(
            options=options,
            description=description,
            layout=widgets.Layout(width=width_map.get(width, LAYOUT["DROPDOWN_WIDTH"])),
        )
        if value is not None:
            radio.value = value
        return radio

    @staticmethod
    def create_filter_row():
        """Create a filter row with consistent dropdown and text input styling"""
        dropdown1 = WidgetFactory.create_dropdown(
            options=["Voc(V)", "Jsc(mA/cm2)", "FF(%)", "PCE(%)", "V_mpp(V)", "J_mpp(mA/cm2)"],
            description="",
            width="label",
        )
        dropdown2 = WidgetFactory.create_dropdown(
            options=[">", ">=", "<", "<=", "==", "!="], description="", width="label"
        )
        text_input = WidgetFactory.create_text_input(
            placeholder="Write a value", description="", width="standard"
        )

        # Update width mapping for label-sized dropdowns
        dropdown1.layout.width = LAYOUT["LABEL_WIDTH"]
        dropdown2.layout.width = LAYOUT["LABEL_WIDTH"]

        return widgets.HBox([dropdown1, dropdown2, text_input])

    @staticmethod
    def create_plot_type_row():
        """Create a plot type selection row with consistent styling"""
        plot_type_dropdown = WidgetFactory.create_dropdown(
            options=["Boxplot", "Paired Boxplot", "Boxplot (omitted)", "Histogram", "JV Curve"],
            description="Plot Type:",
            width="wide",
        )
        option1_dropdown = WidgetFactory.create_dropdown(
            options=[], description="Option 1:", width="extra_wide"
        )
        option2_dropdown = WidgetFactory.create_dropdown(
            options=[], description="Option 2:", width="extra_wide"
        )

        return widgets.HBox([plot_type_dropdown, option1_dropdown, option2_dropdown])


# define functions to get names
def sample_and_curve_name(sample_name, curve_name):
    return sample_name + " " + curve_name


def only_sample_name(sample_name, curve_name):
    return sample_name


def only_curve_name(sample_name, curve_name):
    return curve_name


# class for size and name widgets.
class plot_options(widgets.widget_box.VBox):
    def __init__(self, default_name=0):
        self.width = widgets.BoundedIntText(
            value=1200, min=100, max=2000, step=1, description="width in px:"
        )

        self.height = widgets.BoundedIntText(
            value=500, min=100, max=2000, step=1, description="height in px:"
        )

        self.name = widgets.ToggleButtons(
            options=[
                ("sample + curve name", sample_and_curve_name),
                ("only sample name", only_sample_name),
                ("only individual name", only_curve_name),
            ],
            index=default_name,
            description="select how the datasets will be named",
        )
        super().__init__([self.name, self.width, self.height])


# function to create a manual display area
def create_manual(filename):
    toggle_manual = widgets.ToggleButton(description="Manual")
    manual_out = widgets.Output()

    def update_manual(change):
        manual_out.clear_output()
        if change["new"]:
            with manual_out, open(filename, "r", encoding="utf-8") as file:
                display(Markdown(file.read()))

    toggle_manual.observe(update_manual, names="value")
    return widgets.VBox([toggle_manual, manual_out])
