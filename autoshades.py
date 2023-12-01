from datetime import datetime
from pvlib import location
import json
import numpy as np
import pandas as pd
import requests
import time

# Configuration
LATITUDE, LONGITUDE, TZ = 45.5051, -122.6750, 'America/Los_Angeles'  # Location: Portland, OR
WINDOW_ORIENTATION = 150  # Degrees

# Define the cuboid (desk) and window dimensions
DESK_BOUNDS = {
	"min": np.array([60+12, 108, 30]),
	"max": np.array([122-12, 132, 54])
}

WINDOW_BOUNDS = {
	"Window1": {
		"min": np.array([148, 98, 44]),
		"max": np.array([148, 126, 90]),
		"top_rail_id": "office_1_bottom_up",
		"bottom_rail_id": "office_1_top_down"
	},
	"Window2": {
		"min": np.array([159, 18, 24]),
		"max": np.array([159, 59, 90]),
		"top_rail_id": "office_1_bottom_up",
		"bottom_rail_id": "office_2_top_down"
	}
}

def sun_position(latitude, longitude, tz, times):
	site = location.Location(latitude, longitude, tz=tz)
	return site.get_solarposition(times)

def ray_intersects_cuboid(ray_origin, ray_direction, cuboid_min, cuboid_max):
	# print(f"ray_origin: {ray_origin}, ray_direction: {ray_direction}, cuboid_min: {cuboid_min}, cuboid_max: {cuboid_max}")
	t_near = -np.inf
	t_far = np.inf

	for i in range(3):
		if ray_direction[i] == 0:
			if ray_origin[i] < cuboid_min[i] or ray_origin[i] > cuboid_max[i]:
				return False
		else:
			inv_dir = 1.0 / ray_direction[i]
			t1 = (cuboid_min[i] - ray_origin[i]) * inv_dir
			t2 = (cuboid_max[i] - ray_origin[i]) * inv_dir

			if t1 > t2:
				t1, t2 = t2, t1

			if t1 > t_near:
				t_near = t1
			if t2 < t_far:
				t_far = t2

			if t_near > t_far or t_far < 0:
				return False

	return True

def calculate_shading_requirements(sun_position, desk_min, desk_max, window_min, window_max, window_orientation):
	min_z, max_z = np.inf, -np.inf
	total_rays = 0

	relative_azimuth = sun_position['azimuth'] - WINDOW_ORIENTATION
	if relative_azimuth < 0:
		relative_azimuth += 360
	
	elevation = sun_position['elevation']
	
	# Convert degrees to radians
	relative_azimuth_rads = np.radians(relative_azimuth)
	elevation_rads = np.radians(elevation)

	for y in range(window_min[1], window_max[1]):
		for z in range(window_min[2], window_max[2]):
			ray_origin = np.array([window_min[0], y, z])
			ray_direction = np.array([-np.cos(relative_azimuth_rads),  # X-component
			                          np.sin(relative_azimuth_rads),  # Y-component
			                          -np.sin(elevation_rads)])  # Z-component

			if ray_intersects_cuboid(ray_origin, ray_direction, desk_min, desk_max):
				min_z = min(min_z, z)
				max_z = max(max_z, z)
				total_rays += 1

	window_height = window_max[2] - window_min[2]

	if total_rays == 0:
		# If no rays intersect, the shade should be fully open
		return 0, 0, total_rays, relative_azimuth, elevation

	top_percent = (window_max[2] - max_z) / window_height if max_z != -np.inf else 0
	bottom_percent = (window_max[2] - min_z) / window_height if min_z != np.inf else 1

	return top_percent, bottom_percent, total_rays, relative_azimuth, elevation


##
## Calcuate Current Shade Positions
##

def calculate_current_shade_positions():
	# Get the current time in the specified timezone
	current_time = pd.Timestamp(datetime.now(), tz=TZ)

	# Calculate sun position for the current time
	sun_pos = sun_position(LATITUDE, LONGITUDE, TZ, current_time).iloc[0]

	# Storage for the shade state
	shade_state = {}

	# Calculate shading requirements for each window
	for window_name, bounds in WINDOW_BOUNDS.items():
	    window_min, window_max = bounds["min"], bounds["max"]
	    top_percent, bottom_percent, _, _, _ = calculate_shading_requirements(sun_pos, DESK_BOUNDS["min"], DESK_BOUNDS["max"], window_min, window_max, WINDOW_ORIENTATION)

	    # Convert percentages to positions (0-100 scale, for example)
	    top_position = int(top_percent * 100)
	    bottom_position = 100 - int(bottom_percent * 100)

	    # Store the shade state
	    shade_state[window_name] = {"top": top_position, "bottom": bottom_position}

	return shade_state

##
## Main
##

NODE_RED_ENDPOINT = "http://192.168.0.2:1880/endpoint/autoshades"

while True:
    # Calculate the current shade positions (reuse your existing code here)
    json_output = calculate_current_shade_positions()
    print(json_output)

    # Send the POST request to Node-RED
    response = requests.post(NODE_RED_ENDPOINT, json=json_output)
    print(f"Response: {response.status_code}, {response.text}")

    # Wait for 5 minutes before the next update
    time.sleep(300)



##
## Time Series Generation
##

def generate_time_series():
	import matplotlib.animation as animation
	import matplotlib.dates as mdates
	import matplotlib.pyplot as plt


	# Define your location, date, and time range
	times = pd.date_range('2023-11-29 6:00 -08:00', '2023-11-29 21:00  -08:00', freq='15T')  # 8am to 5pm, in 15-minute increments

	# Results storage
	results = []

	# Iterate over each time and each window to calculate shading requirements
	for time in times:
		sun_pos = sun_position(LATITUDE, LONGITUDE, TZ, time).iloc[0]  # Get sun position for the current time
		desk_min, desk_max = DESK_BOUNDS["min"], DESK_BOUNDS["max"]

		for window_name, bounds in WINDOW_BOUNDS.items():
			window_min, window_max = bounds["min"], bounds["max"]
			top_percent, bottom_percent, total_rays, relative_azimuth, elevation = calculate_shading_requirements(sun_pos, desk_min, desk_max, window_min, window_max, WINDOW_ORIENTATION)

			# Store the results along with sun position
			results.append((time, window_name, top_percent, bottom_percent, total_rays, relative_azimuth, elevation))

	# Create a DataFrame from the results
	df = pd.DataFrame(results, columns=['Timestamp', 'Window', 'Top Rail', 'Bottom Rail', 'Shady Rays', 'Relative Azimuth', 'Elevation'])

	# Display the DataFrame
	print(df.to_string(index=False))


	##
	## Animation
	##

	def create_animation(results):
		fig, axs = plt.subplots(3, 1, figsize=(10, 12), gridspec_kw={'height_ratios': [1, 1, 1]})

		def animate(i):
			# Clear previous contents
			for ax in axs:
				ax.clear()

			# First subplot: Window1 shading
			ax1 = axs[0]
			time1, top1, bottom1 = results[i*2][0], results[i*2][2], results[i*2][3]
			ax1.bar(x=time1, height=bottom1-top1, bottom=top1, width=0.1, color='blue', align='center')
			ax1.set_title('Window1 Shading')
			ax1.set_ylim([1, 0])
			ax1.set_xticks([time1])
			ax1.set_xticklabels([time1.strftime('%H:%M')])

			# Second subplot: Window2 shading
			ax2 = axs[1]
			time2, top2, bottom2 = results[i*2+1][0], results[i*2+1][2], results[i*2+1][3]
			ax2.bar(x=time2, height=bottom2-top2, bottom=top2, width=0.1, color='red', align='center')
			ax2.set_title('Window2 Shading')
			ax2.set_ylim([1, 0])
			ax2.set_xticks([time2])
			ax2.set_xticklabels([time2.strftime('%H:%M')])

			# Third subplot: Sun position scatter plot
			ax3 = axs[2]
			# Extract sun position data for the current frame
			sun_azimuth = results[i*2][5]  # Adjust index based on where azimuth is stored in results
			sun_elevation = results[i*2][6]  # Adjust index based on where elevation is stored in results
			ax3.scatter(sun_azimuth, sun_elevation, color='orange')
			ax3.set_xlim([0, 360])
			ax3.set_ylim([-30, 60])
			ax3.set_xlabel('Relative Azimuth (degrees)')
			ax3.set_ylabel('Elevation (degrees)')
			ax3.set_title('Sun Position at ' + results[i*2][0].strftime('%H:%M'))

			fig.suptitle('Shading Requirements and Sun Position Over Time')

		ani = animation.FuncAnimation(fig, animate, frames=len(times), interval=200)
		plt.show()
		return ani

	# Call the function to create the animation
	animation_obj = create_animation(results)

	# import os
	# os.environ['PATH'] += os.pathsep + '/opt/homebrew/bin'
	# print(os.environ['PATH'])
	# animation_obj.save('/Users/mthole/Desktop/animation.mp4', writer='ffmpeg', fps=10, bitrate=1800)



