# One absolute straight-line move in machine coordinates.
#
# The pen state is encoded in Z: the caller inserts z_up / z_down points
# itself. The PLC has no per-point speed: velocity/acceleration/jerk are
# global and are set with the params contract before a trajectory.
#
# Units: mm. Coordinates use the paper frame: origin at the lower-left
# corner, +X right, +Y up, paper surface at the configured z_down.
float64 x
float64 y
float64 z