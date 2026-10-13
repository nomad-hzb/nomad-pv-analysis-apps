import logging

import gui_components as gui
import ipywidgets as widgets
import utils
from IPython.display import HTML, display

logger = logging.getLogger(__name__)


def setup_app():
    """Setup and return the complete application"""

    # Generated-image state, shared by the closures below.
    current_image = None
    current_params = None

    # Create GUI components
    size_box, width_input, height_input = gui.create_size_inputs(
        default_width=25, default_height=25
    )
    margin_box, margins = gui.create_margin_inputs(default_margin=3)
    dpi_box, dpi_input = gui.create_dpi_input(default_dpi=350)
    pattern_box, pattern_type, black_percentage = gui.create_pattern_controls(default_percentage=50)
    format_box, format_selector, include_inverted = gui.create_file_format_selector()
    button_box, generate_btn, download_btn = gui.create_action_buttons()
    display_box, output_area = gui.create_output_display()

    def generate_image(b):
        """Generate bitmap image based on current parameters"""
        nonlocal current_image, current_params

        with output_area:
            output_area.clear_output(wait=True)

            try:
                # Get parameters
                width_mm = width_input.value
                height_mm = height_input.value
                dpi = dpi_input.value

                margin_dict = {
                    "top": margins["top"].value,
                    "bottom": margins["bottom"].value,
                    "left": margins["left"].value,
                    "right": margins["right"].value,
                }

                black_pct = black_percentage.value
                pattern = pattern_type.value

                # Parse pattern type and kwargs
                kwargs = {}
                if pattern.startswith("complementary_"):
                    pattern_id = 0 if pattern.endswith("_a") else 1
                    pattern_base = "complementary"
                    kwargs["pattern_id"] = pattern_id
                elif pattern.startswith("publication_"):
                    base_size = int(pattern.split("_")[1])
                    pattern_base = "publication"
                    kwargs["base_size"] = base_size
                else:
                    pattern_base = pattern

                # Generate image
                logger.info("Generating %sx%smm image at %s DPI", width_mm, height_mm, dpi)
                img = utils.create_bitmap(
                    width_mm, height_mm, dpi, margin_dict, black_pct, pattern_base, **kwargs
                )

                current_image = img
                current_params = {
                    "width": width_mm,
                    "height": height_mm,
                    "dpi": dpi,
                    "pattern": pattern,
                    "black_pct": black_pct,
                    "achieved_pct": utils.black_coverage(img, margin_dict, dpi),
                    "margins": margin_dict,
                }

                # Display image(s)
                format_str = format_selector.value

                # Display original
                display(HTML("<h4>Original:</h4>"))
                img_base64 = utils.image_to_base64(img, format=format_str)
                display(
                    HTML(
                        f'<img src="{img_base64}" style="max-width: 100%; border: 1px solid #ccc;"/>'  # noqa: E501
                    )
                )

                # Display inverted if checkbox is selected
                if include_inverted.value:
                    inverted_img = utils.invert_image(img, width_mm, height_mm, dpi, margin_dict)
                    inverted_base64 = utils.image_to_base64(inverted_img, format=format_str)
                    display(HTML('<h4 style="margin-top: 20px;">Inverted:</h4>'))
                    display(
                        HTML(
                            f'<img src="{inverted_base64}" style="max-width: 100%; border: 1px solid #ccc;"/>'  # noqa: E501
                        )
                    )

                # Show info
                width_px = utils.mm_to_pixels(width_mm, dpi)
                height_px = utils.mm_to_pixels(height_mm, dpi)
                achieved = current_params["achieved_pct"]
                logger.info("Image generated: %sx%s pixels", width_px, height_px)
                logger.info(
                    "Pattern: %s, black %.1f%% (asked %.1f%%)", pattern, achieved, black_pct
                )
                print(f"Image: {width_px} x {height_px} pixels ({width_mm} x {height_mm} mm)")
                print(f"Pattern: {pattern}. Black: {achieved:.1f}% (requested {black_pct:.1f}%)")

                # Enable download
                download_btn.disabled = False

            except Exception as e:
                logger.exception("Error generating image: %s", e)
                print(f"Could not generate the image: {e}")

    def download_image(b):
        """Create download link for current image"""
        nonlocal current_image, current_params

        if current_image is None:
            logger.warning("No image to download. Please generate an image first.")
            with output_area:
                print("No image to download yet. Click Generate first.")
            return

        with output_area:
            output_area.clear_output(wait=True)

            try:
                # Generate filename
                format_str = format_selector.value
                params = current_params
                base_filename = f"bitmap_{params['width']:.0f}x{params['height']:.0f}mm_{params['dpi']}dpi_{params['achieved_pct']:.1f}pct"  # noqa: E501
                filename = f"{base_filename}.{format_str.lower()}"

                # Create download link for original
                download_link = gui.create_download_link(
                    utils.to_binary_image(current_image), filename, format_str
                )
                display(download_link)

                # Create inverted version if requested
                if include_inverted.value:
                    params = current_params
                    inverted_img = utils.invert_image(
                        current_image,
                        params["width"],
                        params["height"],
                        params["dpi"],
                        params["margins"],
                    )
                    inverted_filename = f"{base_filename}_inverted.{format_str.lower()}"
                    inverted_link = gui.create_download_link(
                        utils.to_binary_image(inverted_img), inverted_filename, format_str
                    )
                    display(
                        HTML("<p style='margin-top: 10px;'><strong>Inverted version:</strong></p>")
                    )
                    display(inverted_link)

                # Show the image(s) again
                img_base64 = utils.image_to_base64(current_image, format=format_str)
                display(HTML('<h4 style="margin-top: 20px;">Original:</h4>'))
                display(
                    HTML(
                        f'<img src="{img_base64}" style="max-width: 100%; border: 1px solid #ccc;"/>'  # noqa: E501
                    )
                )

                if include_inverted.value:
                    params = current_params
                    inverted_img = utils.invert_image(
                        current_image,
                        params["width"],
                        params["height"],
                        params["dpi"],
                        params["margins"],
                    )
                    inverted_base64 = utils.image_to_base64(inverted_img, format=format_str)
                    display(HTML('<h4 style="margin-top: 20px;">Inverted:</h4>'))
                    display(
                        HTML(
                            f'<img src="{inverted_base64}" style="max-width: 100%; border: 1px solid #ccc;"/>'  # noqa: E501
                        )
                    )

                print("Click the button(s) above to download.")

            except Exception as e:
                logger.exception("Error creating download: %s", e)
                print(f"Could not create the download: {e}")

    # Attach event handlers
    generate_btn.on_click(generate_image)
    download_btn.on_click(download_image)

    # Create main layout
    header = widgets.HTML(
        "<h1 style='text-align: center; color: #333;'>Bitmap Image Generator</h1>"
        "<p style='text-align: center; color: #666;'>Create black & white bitmap images with customizable patterns for combinatorial inkjet printing</p>"  # noqa: E501
    )

    # The controls keep their width: in a flex row a wide preview image used to squeeze this
    # column down to a few pixels after the first Generate, leaving only the preview visible.
    controls = widgets.VBox(
        [size_box, margin_box, dpi_box, pattern_box, format_box, button_box],
        layout=widgets.Layout(padding="10px", flex="0 0 auto", min_width="340px"),
    )
    display_box.layout = widgets.Layout(flex="1 1 0", min_width="0", overflow="auto")

    app_layout = widgets.VBox(
        [
            header,
            widgets.HBox([controls, display_box], layout=widgets.Layout(width="100%")),
        ],
        layout=widgets.Layout(padding="20px"),
    )

    return app_layout
