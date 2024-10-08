import shutil
import logging
from dataUtils.get_poly import simplify_polygon, validate_polygon, get_huc_polygon
import os
import datetime
import rasterio
from rasterio.plot import show
import numpy as np
from rasterio.mask import mask
from shapely.geometry import box
from dataUtils.get_poly import check_polygon_intersection, get_huc_polygon, validate_polygon, simplify_polygon
from dataUtils.data_utils import appeears_login, appeears_logout, load_vars, get_earthdata_auth, get_smap_data_bounds
import time
import tempfile
import argparse
import requests
import json
from mpl_toolkits.axes_grid1 import make_axes_locatable
from shapely import Polygon
import importlib.util
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as mplPolygon
matplotlib_spec = importlib.util.find_spec("matplotlib")
matplotlib_available = matplotlib_spec is not None

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_vars()

def check_appeears_product(product_id, layer_name):
    """
    Check if the specified product and layer are available in AppEEARS.
    """
    # First, get the list of all products
    products_url = "https://appeears.earthdatacloud.nasa.gov/api/product"
    
    try:
        response = requests.get(products_url, headers=None, timeout=30)
        response.raise_for_status()
        
        # Print raw response for debugging
        print("Raw API Response:")
        print(response.text[:1000])  # Print first 1000 characters
        
        products = response.json()
        
        print(f"Type of products: {type(products)}")
        
        if isinstance(products, list):
            print("Products is a list. Printing first item:")
            print(products[0] if products else "Empty list")
        elif isinstance(products, dict):
            print("Products is a dictionary. Printing keys:")
            print(products.keys())
        else:
            print(f"Unexpected type for products: {type(products)}")
        
        print("Available Soil Moisture Products:")
        if isinstance(products, list):
            for product in products:
                if isinstance(product, dict) and 'ProductAndVersion' in product:
                    # Check if the product is related to soil moisture
                    if 'soil moisture' in product.get('Description', '').lower():
                        print(f"- {product['ProductAndVersion']}: {product.get('Description', 'N/A')}")
                        print(f"  Available: {product.get('Available', 'N/A')}")
                        print(f"  Temporal Extent: {product.get('TemporalExtentStart', 'N/A')} to {product.get('TemporalExtentEnd', 'N/A')}")
                        print(f"  Resolution: {product.get('Resolution', 'N/A')}")
                        print(f"  Source: {product.get('Source', 'N/A')}")
                        print("  ---")
        
    except requests.Timeout:
        logging.error("Request timed out while checking product availability")
        return False
    except requests.RequestException as e:
        logging.error(f"Error checking product availability: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return False

    return True  # Return True for now, adjust based on actual product availability check

def get_product_layers(token, product_id):
    """
    Get available layers for a specific product from AppEEARS API.
    """
    url = f"https://appeears.earthdatacloud.nasa.gov/api/product/{product_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        product_info = response.json()
        
        logging.info(f"Available layers for {product_id}:")
        for layer_name, layer_info in product_info.items():
            logging.info(f"- {layer_name}: {layer_info.get('Description', 'No description available')}")
        
        return product_info
    except requests.RequestException as e:
        logging.error(f"Error getting product layers: {e}")
        return {}

def submit_appears_task(token, polygon, start_date, end_date):
    """
    Submit a task to AppEEARS API for SMAP data retrieval.
    """
    product_id = "SPL3SMP_E.006"
    layers = get_product_layers(token, product_id)
    
    if not layers:
        logging.error(f"No layers found for product {product_id}")
        return None
    
    # Choose the first available layer related to soil moisture
    soil_moisture_layer = next((layer_name for layer_name, layer_info in layers.items() 
                                if 'soil_moisture' in layer_name.lower() or 'soil_moisture' in layer_info.get('Description', '').lower()), 
                               None)
    
    if not soil_moisture_layer:
        logging.error(f"No soil moisture layer found for product {product_id}")
        return None
    
    logging.info(f"Selected layer: {soil_moisture_layer}")
    
    url = "https://appeears.earthdatacloud.nasa.gov/api/task"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    task_payload = {
        "task_type": "area",
        "task_name": "SMAP_Soil_Moisture_Extraction",
        "params": {
            "dates": [
                {
                    "startDate": start_date.strftime("%m-%d-%Y"),
                    "endDate": end_date.strftime("%m-%d-%Y")
                }
            ],
            "layers": [
                {
                    "product": product_id,
                    "layer": soil_moisture_layer
                }
            ],
            "output": {
                "format": {
                    "type": "geotiff"
                },
                "projection": "geographic"
            },
            "geo": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [polygon]
                        }
                    }
                ]
            }
        }
    }
    
    try:
        logging.info(f"Submitting task to URL: {url}")
        logging.info(f"Headers: {headers}")
        logging.info(f"Payload: {json.dumps(task_payload, indent=2)}")
        
        response = requests.post(url, headers=headers, data=json.dumps(task_payload), timeout=30)
        
        logging.info(f"Response status code: {response.status_code}")
        logging.info(f"Response headers: {response.headers}")
        logging.info(f"Response content: {response.text}")
        
        if response.status_code == 202:
            return response.json()["task_id"]
        else:
            logging.error(f"Failed to submit task. Status code: {response.status_code}")
            logging.error(f"Response: {response.text}")
            return None
    except requests.Timeout:
        logging.error("Request timed out while submitting task")
        return None
    except requests.RequestException as e:
        logging.error(f"Error submitting task: {e}")
        return None
    
def check_task_status(token, task_id):
    """
    Check the status of an AppEEARS task.
    """
    url = f"https://appeears.earthdatacloud.nasa.gov/api/task/{task_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()["status"]
    else:
        logging.error(f"Failed to check task status. Status code: {response.status_code}")
        return None

def download_task_results(token, task_id, output_dir):
    """
    Download the results of a completed AppEEARS task.
    """
    url = f"https://appeears.earthdatacloud.nasa.gov/api/bundle/{task_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        bundle_info = response.json()
        for file_info in bundle_info["files"]:
            file_id = file_info["file_id"]
            file_name = file_info["file_name"]
            download_url = f"https://appeears.earthdatacloud.nasa.gov/api/bundle/{task_id}/{file_id}"
            
            file_response = requests.get(download_url, headers=headers, allow_redirects=True)
            if file_response.status_code == 200:
                with open(f"{output_dir}/{file_name}", "wb") as f:
                    f.write(file_response.content)
                logging.info(f"Downloaded: {file_name}")
            else:
                logging.error(f"Failed to download {file_name}. Status code: {file_response.status_code}")
    else:
        logging.error(f"Failed to get bundle info. Status code: {response.status_code}")

def extract_soil_moisture_from_geotiff(geotiff_path, polygon):
    """
    Extract soil moisture data for the given polygon from the GeoTIFF file using rasterio.
    """
    try:
        with rasterio.open(geotiff_path) as src:
            # Create a GeoJSON-like geometry object
            geom = {"type": "Polygon", "coordinates": [polygon]}
            
            # Mask the raster with the polygon
            out_image, out_transform = mask(src, [geom], crop=True)
            
            # Get the data from the masked raster
            data = out_image[0]  # Assuming it's a single-band raster
            
            # Calculate average soil moisture
            valid_data = data[data != src.nodata]
            if len(valid_data) > 0:
                average_moisture = np.mean(valid_data)
                return average_moisture
            else:
                logging.warning("No valid data found within the polygon")
                return None
        
    except Exception as e:
        logging.error(f"Error extracting soil moisture data: {e}")
        logging.error("Traceback: ", exc_info=True)
        return None

def visualize_smap_data(geotiff_path, polygon, average_moisture):
    """
    Create a detailed visualization of SMAP data with the polygon overlay.
    """
    try:
        with rasterio.open(geotiff_path) as src:
            fig, ax = plt.subplots(figsize=(12, 8))
            
            # Plot the SMAP data
            show(src, ax=ax, cmap='YlGnBu')
            
            # Plot the polygon
            poly = mplPolygon(polygon, facecolor='none', edgecolor='red', linewidth=2)
            ax.add_patch(poly)
            
            # Add colorbar
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="5%", pad=0.05)
            plt.colorbar(ax.images[0], cax=cax, label='Soil Moisture')
            
            # Set the extent to focus on the polygon
            min_lon, min_lat, max_lon, max_lat = Polygon(polygon).bounds
            ax.set_xlim(min_lon - 0.5, max_lon + 0.5)
            ax.set_ylim(min_lat - 0.5, max_lat + 0.5)
            
            # Add title and labels
            plt.title(f'SMAP Soil Moisture Data with HUC8 Polygon\nAverage Soil Moisture: {average_moisture:.4f}')
            plt.xlabel('Longitude')
            plt.ylabel('Latitude')
            
            # Add grid
            ax.grid(True, linestyle='--', alpha=0.5)
            
            # Show the plot
            plt.tight_layout()
            plt.show()
            
    except Exception as e:
        logging.error(f"Error visualizing SMAP data: {e}")
        logging.error("Traceback: ", exc_info=True)

# Add a function to verify the token:
def verify_token(token):
    url = "https://appeears.earthdatacloud.nasa.gov/api/user"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            logging.info("Token verified successfully")
            return True
        else:
            logging.error(f"Failed to verify token. Status code: {response.status_code}")
            logging.error(f"Response: {response.text}")
            return False
    except requests.RequestException as e:
        logging.error(f"Error verifying token: {e}")
        return False

def main(start_date, end_date, lat, lon, visual):
    # Login to AppEEARS
    token = appeears_login()
    if not token:
        logging.error("Failed to login to AppEEARS. Please check your credentials.")
        return

    # Check if the product and layer are available
    product_id = "SPL3SMP_E.003"
    layer_name = "soil_moisture"
    if not check_appeears_product(product_id, layer_name):
        logging.error("Required product or layer is not available. Exiting.")
        appeears_logout()
        return

    # Get the HUC8 polygon
    huc8_polygon = get_huc_polygon(lat, lon, 8)
    if not huc8_polygon:
        logging.error("Failed to retrieve HUC8 polygon")
        appeears_logout()
        return

    # Simplify & validate the polygon
    simplified_polygon = simplify_polygon(huc8_polygon)
    simplified_polygon = validate_polygon(simplified_polygon)
    logging.debug(f"Validated polygon coordinates: {simplified_polygon}")

    # Submit AppEEARS task
    task_id = submit_appears_task(token, simplified_polygon, start_date, end_date)
    if not task_id:
        logging.error("Failed to submit AppEEARS task")
        appeears_logout()
        return

    # Wait for task to complete
    max_retries = 30  # 30 minutes maximum wait time
    retries = 0
    while retries < max_retries:
        status = check_task_status(token, task_id)
        if status == "done":
            logging.info("Task completed successfully")
            break
        elif status == "error":
            logging.error("Task failed")
            appeears_logout()
            return
        elif status is None:
            logging.error("Failed to check task status")
            appeears_logout()
            return
        time.sleep(60)  # Wait for 60 seconds before checking again
        retries += 1
    else:
        logging.error("Task did not complete within the maximum wait time")
        appeears_logout()
        return
    
    # Download results
    output_dir = tempfile.mkdtemp()
    download_task_results(token, task_id, output_dir)

    # Process and visualize results
    geotiff_file = next((f for f in os.listdir(output_dir) if f.endswith('.tif')), None)
    if geotiff_file:
        geotiff_path = os.path.join(output_dir, geotiff_file)
        average_soil_moisture = extract_soil_moisture_from_geotiff(geotiff_path, simplified_polygon)
        
        if average_soil_moisture is not None:
            logging.info(f"Average soil moisture: {average_soil_moisture:.4f}")
            
            if visual:
                visualize_smap_data(geotiff_path, simplified_polygon, average_soil_moisture)
        else:
            logging.error("Failed to calculate average soil moisture")
    else:
        logging.error("No GeoTIFF file found in the downloaded results")

    # Clean up
    shutil.rmtree(output_dir)
    
    # Logout from AppEEARS
    appeears_logout()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Calculate average soil moisture for a HUC8 polygon from SMAP L3 data.')
    parser.add_argument('--start-date', type=lambda d: datetime.datetime.strptime(d, '%Y-%m-%d').date(), required=True, help='Start Date in YYYY-MM-DD format')
    parser.add_argument('--end-date', type=lambda d: datetime.datetime.strptime(d, '%Y-%m-%d').date(), required=True, help='End Date in YYYY-MM-DD format')
    parser.add_argument('--lat', type=float, required=True, help='Latitude of the point within the desired HUC8 polygon')
    parser.add_argument('--lon', type=float, required=True, help='Longitude of the point within the desired HUC8 polygon')
    parser.add_argument('--visual', action='store_true', help='Enable matplotlib visualization')
    args = parser.parse_args()

    main(args.start_date, args.end_date, args.lat, args.lon, args.visual)