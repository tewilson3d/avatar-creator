#!/usr/bin/env python3
"""
Standalone Quad Remesh - Python CLI Tool
Remesh OBJ/PLY files using QuadriFlow and Instant Meshes

This script runs in any standard Python environment (no Blender/Maya required).

Usage:
    # QuadriFlow remesh
    python standalone_quad_remesh.py input.obj -o output.obj --method quadriflow --faces 5000
    
    # Instant Meshes remesh  
    python standalone_quad_remesh.py input.obj -o output.obj --method instant --vertices 5000
    
    # Batch process a folder
    python standalone_quad_remesh.py ./meshes/ -o ./remeshed/ --method quadriflow --faces 2000

As a module:
    import standalone_quad_remesh as remesh
    
    # QuadriFlow
    remesh.quadriflow('input.obj', 'output.obj', target_faces=5000)
    
    # Instant Meshes
    remesh.instant_meshes('input.obj', 'output.obj', target_vertices=5000)
"""

import os
import sys
import platform
import subprocess
import tempfile
import time
import argparse
import glob
from pathlib import Path
from typing import Optional, List, Dict, Any

__version__ = "1.0.0"
__author__ = "ExeDev"

# ============================================================================
# Configuration
# ============================================================================

def get_script_dir() -> str:
    """Get the directory containing this script"""
    return os.path.dirname(os.path.realpath(__file__))


def get_executable_path(name: str) -> Optional[str]:
    """
    Find an executable (instant-meshes or quadriflow)
    
    Search order:
    1. Environment variable (INSTANT_MESHES_PATH or QUADRIFLOW_PATH)
    2. bin/ or bin-windows/ folder next to this script
    3. Same folder as this script
    4. System PATH (/usr/local/bin, /usr/bin)
    
    Args:
        name: Executable name ('instant-meshes' or 'quadriflow')
        
    Returns:
        Path to executable or None if not found
    """
    is_windows = platform.system() == 'Windows'
    script_dir = get_script_dir()
    
    # Check environment variable first
    env_var = name.upper().replace('-', '_') + '_PATH'
    env_path = os.environ.get(env_var)
    if env_path and os.path.isfile(env_path):
        return env_path
    
    if is_windows:
        exe_name = name + '.exe'
        paths = [
            os.path.join(script_dir, 'bin-windows', exe_name),
            os.path.join(script_dir, 'bin', exe_name),
            os.path.join(script_dir, exe_name),
        ]
    else:
        paths = [
            os.path.join(script_dir, 'bin', name),
            os.path.join(script_dir, name),
            f'/usr/local/bin/{name}',
            f'/usr/bin/{name}',
        ]
    
    for p in paths:
        if os.path.isfile(p):
            return p
    
    return None


def get_instant_meshes_path() -> Optional[str]:
    """Find the Instant Meshes executable"""
    return get_executable_path('instant-meshes')


def get_quadriflow_path() -> Optional[str]:
    """Find the QuadriFlow executable"""
    return get_executable_path('quadriflow')


# ============================================================================
# Mesh Info Utilities
# ============================================================================

def get_obj_stats(filepath: str) -> Dict[str, int]:
    """
    Get basic statistics from an OBJ file
    
    Args:
        filepath: Path to OBJ file
        
    Returns:
        Dict with 'vertices', 'faces', 'triangles', 'quads' counts
    """
    vertices = 0
    faces = 0
    triangles = 0
    quads = 0
    
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('v '):
                vertices += 1
            elif line.startswith('f '):
                faces += 1
                # Count vertex indices in face
                parts = line.split()[1:]
                num_verts = len(parts)
                if num_verts == 3:
                    triangles += 1
                elif num_verts == 4:
                    quads += 1
    
    return {
        'vertices': vertices,
        'faces': faces,
        'triangles': triangles,
        'quads': quads
    }


def print_mesh_stats(filepath: str, label: str = "") -> Dict[str, int]:
    """Print mesh statistics"""
    stats = get_obj_stats(filepath)
    prefix = f"{label}: " if label else ""
    print(f"{prefix}{stats['vertices']} vertices, {stats['faces']} faces "
          f"({stats['triangles']} tris, {stats['quads']} quads)")
    return stats


# ============================================================================
# QuadriFlow Remeshing
# ============================================================================

def quadriflow(
    input_path: str,
    output_path: str,
    target_faces: int = 5000,
    preserve_sharp: bool = False,
    preserve_boundary: bool = False,
    adaptive: bool = False,
    mcf: bool = False,
    seed: int = 0,
    quiet: bool = False,
    timeout: int = 600
) -> bool:
    """
    Remesh a mesh file using QuadriFlow
    
    Args:
        input_path: Path to input mesh (OBJ, PLY)
        output_path: Path for output mesh (OBJ)
        target_faces: Target number of quad faces
        preserve_sharp: Preserve sharp edges
        preserve_boundary: Preserve mesh boundaries  
        adaptive: Use adaptive scale
        mcf: Use minimum cost flow solver
        seed: Random seed for reproducibility (0 = random)
        quiet: Suppress output messages
        timeout: Timeout in seconds (default 600 = 10 minutes)
        
    Returns:
        True on success, False on failure
    """
    quadriflow_path = get_quadriflow_path()
    if not quadriflow_path:
        print("ERROR: QuadriFlow executable not found.", file=sys.stderr)
        print("Set QUADRIFLOW_PATH environment variable or place executable in bin/ folder.", 
              file=sys.stderr)
        return False
    
    if not os.path.isfile(input_path):
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        return False
    
    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    if not quiet:
        print(f"QuadriFlow: {input_path} -> {output_path}")
        print(f"  Target faces: {target_faces}")
        input_stats = print_mesh_stats(input_path, "  Input")
    
    start_time = time.time()
    
    # Build command
    cmd = [
        quadriflow_path,
        '-i', input_path,
        '-o', output_path,
        '-f', str(target_faces)
    ]
    
    if preserve_sharp:
        cmd.append('-sharp')
    if preserve_boundary:
        cmd.append('-boundary')
    if adaptive:
        cmd.append('-adaptive')
    if mcf:
        cmd.append('-mcf')
    if seed > 0:
        cmd.extend(['-seed', str(seed)])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode != 0:
            print(f"ERROR: QuadriFlow failed with code {result.returncode}", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print(f"ERROR: QuadriFlow timed out after {timeout} seconds", file=sys.stderr)
        return False
    except Exception as e:
        print(f"ERROR: Failed to run QuadriFlow: {e}", file=sys.stderr)
        return False
    
    if not os.path.exists(output_path):
        print("ERROR: QuadriFlow did not produce output file", file=sys.stderr)
        return False
    
    elapsed = time.time() - start_time
    
    if not quiet:
        output_stats = print_mesh_stats(output_path, "  Output")
        print(f"  Completed in {elapsed:.2f}s")
    
    return True


# ============================================================================
# Instant Meshes Remeshing
# ============================================================================

def instant_meshes(
    input_path: str,
    output_path: str,
    target_vertices: int = 0,
    edge_length: float = 0.0,
    smooth_iterations: int = 2,
    rosy: int = 4,
    posy: int = 4,
    deterministic: bool = False,
    dominant: bool = False,
    intrinsic: bool = True,
    quiet: bool = False,
    timeout: int = 600
) -> bool:
    """
    Remesh a mesh file using Instant Meshes
    
    Args:
        input_path: Path to input mesh (OBJ, PLY)
        output_path: Path for output mesh (OBJ, PLY)
        target_vertices: Target vertex count (0 = auto)
        edge_length: Target edge length (0 = auto from vertex count)
        smooth_iterations: Post-processing smoothing iterations
        rosy: Rotational symmetry (2, 4, or 6)
        posy: Position symmetry (3, 4, or 6)
        deterministic: Use deterministic mode for reproducible results
        dominant: Allow triangles in output (tri/quad dominant)
        intrinsic: Use intrinsic mode (better for curved surfaces)
        quiet: Suppress output messages
        timeout: Timeout in seconds (default 600 = 10 minutes)
        
    Returns:
        True on success, False on failure
    """
    instant_path = get_instant_meshes_path()
    if not instant_path:
        print("ERROR: Instant Meshes executable not found.", file=sys.stderr)
        print("Set INSTANT_MESHES_PATH environment variable or place executable in bin/ folder.",
              file=sys.stderr)
        return False
    
    if not os.path.isfile(input_path):
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        return False
    
    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    if not quiet:
        print(f"Instant Meshes: {input_path} -> {output_path}")
        if target_vertices > 0:
            print(f"  Target vertices: {target_vertices}")
        elif edge_length > 0:
            print(f"  Edge length: {edge_length}")
        else:
            print(f"  Auto resolution")
        input_stats = print_mesh_stats(input_path, "  Input")
    
    start_time = time.time()
    
    # Build command
    cmd = [
        instant_path,
        '-o', output_path,
        '-r', str(rosy),
        '-p', str(posy),
        '-S', str(smooth_iterations)
    ]
    
    if target_vertices > 0:
        cmd.extend(['-v', str(target_vertices)])
    elif edge_length > 0:
        cmd.extend(['-s', str(edge_length)])
    
    if deterministic:
        cmd.append('-d')
    if dominant:
        cmd.append('-D')
    if intrinsic:
        cmd.append('-i')
    
    # Input file must be last
    cmd.append(input_path)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode != 0:
            print(f"ERROR: Instant Meshes failed with code {result.returncode}", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print(f"ERROR: Instant Meshes timed out after {timeout} seconds", file=sys.stderr)
        return False
    except Exception as e:
        print(f"ERROR: Failed to run Instant Meshes: {e}", file=sys.stderr)
        return False
    
    if not os.path.exists(output_path):
        print("ERROR: Instant Meshes did not produce output file", file=sys.stderr)
        return False
    
    elapsed = time.time() - start_time
    
    if not quiet:
        output_stats = print_mesh_stats(output_path, "  Output")
        print(f"  Completed in {elapsed:.2f}s")
    
    return True


# ============================================================================
# Batch Processing
# ============================================================================

def batch_remesh(
    input_paths: List[str],
    output_dir: str,
    method: str = 'quadriflow',
    suffix: str = '_remeshed',
    **kwargs
) -> Dict[str, bool]:
    """
    Batch remesh multiple files
    
    Args:
        input_paths: List of input file paths
        output_dir: Output directory
        method: 'quadriflow' or 'instant'
        suffix: Suffix to add to output filenames
        **kwargs: Arguments passed to remesh function
        
    Returns:
        Dict mapping input paths to success status
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    results = {}
    total_start = time.time()
    
    remesh_func = quadriflow if method == 'quadriflow' else instant_meshes
    
    print(f"Batch remeshing {len(input_paths)} files with {method}...")
    print(f"Output directory: {output_dir}")
    print()
    
    for i, input_path in enumerate(input_paths, 1):
        basename = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(output_dir, f"{basename}{suffix}.obj")
        
        print(f"[{i}/{len(input_paths)}] Processing {os.path.basename(input_path)}")
        
        success = remesh_func(input_path, output_path, **kwargs)
        results[input_path] = success
        
        if not success:
            print(f"  FAILED")
        print()
    
    # Summary
    succeeded = sum(1 for v in results.values() if v)
    failed = len(results) - succeeded
    total_time = time.time() - total_start
    
    print(f"Batch complete: {succeeded} succeeded, {failed} failed in {total_time:.2f}s")
    
    return results


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    """Command-line interface"""
    parser = argparse.ArgumentParser(
        description='Standalone Quad Remesh - Remesh OBJ/PLY files using QuadriFlow or Instant Meshes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # QuadriFlow with 5000 target faces
  %(prog)s input.obj -o output.obj --method quadriflow --faces 5000
  
  # Instant Meshes with 5000 target vertices
  %(prog)s input.obj -o output.obj --method instant --vertices 5000
  
  # Batch process folder
  %(prog)s ./meshes/*.obj -o ./remeshed/ --method quadriflow --faces 2000
  
  # Check available executables
  %(prog)s --check
"""
    )
    
    parser.add_argument('input', nargs='*', help='Input mesh file(s) or directory')
    parser.add_argument('-o', '--output', help='Output file or directory')
    parser.add_argument('--method', '-m', choices=['quadriflow', 'instant'], 
                        default='quadriflow', help='Remeshing method (default: quadriflow)')
    
    # QuadriFlow options
    qf_group = parser.add_argument_group('QuadriFlow options')
    qf_group.add_argument('--faces', '-f', type=int, default=5000,
                          help='Target face count (default: 5000)')
    qf_group.add_argument('--sharp', action='store_true',
                          help='Preserve sharp edges')
    qf_group.add_argument('--boundary', action='store_true',
                          help='Preserve mesh boundaries')
    qf_group.add_argument('--adaptive', action='store_true',
                          help='Use adaptive scale')
    qf_group.add_argument('--mcf', action='store_true',
                          help='Use minimum cost flow solver')
    qf_group.add_argument('--seed', type=int, default=0,
                          help='Random seed (0 = random)')
    
    # Instant Meshes options
    im_group = parser.add_argument_group('Instant Meshes options')
    im_group.add_argument('--vertices', '-v', type=int, default=0,
                          help='Target vertex count (0 = auto)')
    im_group.add_argument('--edge-length', '-s', type=float, default=0.0,
                          help='Target edge length (0 = auto)')
    im_group.add_argument('--smooth', '-S', type=int, default=2,
                          help='Smoothing iterations (default: 2)')
    im_group.add_argument('--rosy', type=int, default=4, choices=[2, 4, 6],
                          help='Rotational symmetry (default: 4)')
    im_group.add_argument('--posy', type=int, default=4, choices=[3, 4, 6],
                          help='Position symmetry (default: 4)')
    im_group.add_argument('--deterministic', '-d', action='store_true',
                          help='Deterministic mode for reproducible results')
    im_group.add_argument('--dominant', '-D', action='store_true',
                          help='Allow triangles in output')
    im_group.add_argument('--no-intrinsic', action='store_true',
                          help='Disable intrinsic mode')
    
    # General options
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Suppress output messages')
    parser.add_argument('--timeout', '-t', type=int, default=600,
                        help='Timeout in seconds (default: 600)')
    parser.add_argument('--suffix', default='_remeshed',
                        help='Suffix for batch output files (default: _remeshed)')
    parser.add_argument('--check', action='store_true',
                        help='Check for available executables and exit')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    
    args = parser.parse_args()
    
    # Check mode
    if args.check:
        print("Standalone Quad Remesh - Executable Check")
        print("="*50)
        
        qf_path = get_quadriflow_path()
        im_path = get_instant_meshes_path()
        
        print(f"QuadriFlow:      {qf_path if qf_path else 'NOT FOUND'}")
        print(f"Instant Meshes:  {im_path if im_path else 'NOT FOUND'}")
        print()
        print(f"Script directory: {get_script_dir()}")
        print()
        
        if not qf_path and not im_path:
            print("No executables found. Place them in bin/ folder or set environment variables.")
            return 1
        return 0
    
    # Require input
    if not args.input:
        parser.print_help()
        return 1
    
    # Expand globs and collect input files
    input_files = []
    for pattern in args.input:
        if os.path.isdir(pattern):
            # Directory - find all OBJ/PLY files
            input_files.extend(glob.glob(os.path.join(pattern, '*.obj')))
            input_files.extend(glob.glob(os.path.join(pattern, '*.ply')))
        elif '*' in pattern or '?' in pattern:
            # Glob pattern
            input_files.extend(glob.glob(pattern))
        elif os.path.isfile(pattern):
            input_files.append(pattern)
        else:
            print(f"WARNING: Input not found: {pattern}", file=sys.stderr)
    
    if not input_files:
        print("ERROR: No input files found", file=sys.stderr)
        return 1
    
    # Determine output
    if len(input_files) == 1 and args.output and not os.path.isdir(args.output):
        # Single file mode
        output_path = args.output
        
        if args.method == 'quadriflow':
            success = quadriflow(
                input_files[0],
                output_path,
                target_faces=args.faces,
                preserve_sharp=args.sharp,
                preserve_boundary=args.boundary,
                adaptive=args.adaptive,
                mcf=args.mcf,
                seed=args.seed,
                quiet=args.quiet,
                timeout=args.timeout
            )
        else:
            success = instant_meshes(
                input_files[0],
                output_path,
                target_vertices=args.vertices,
                edge_length=args.edge_length,
                smooth_iterations=args.smooth,
                rosy=args.rosy,
                posy=args.posy,
                deterministic=args.deterministic,
                dominant=args.dominant,
                intrinsic=not args.no_intrinsic,
                quiet=args.quiet,
                timeout=args.timeout
            )
        
        return 0 if success else 1
    
    else:
        # Batch mode
        output_dir = args.output or './remeshed'
        
        if args.method == 'quadriflow':
            kwargs = {
                'target_faces': args.faces,
                'preserve_sharp': args.sharp,
                'preserve_boundary': args.boundary,
                'adaptive': args.adaptive,
                'mcf': args.mcf,
                'seed': args.seed,
                'quiet': args.quiet,
                'timeout': args.timeout
            }
        else:
            kwargs = {
                'target_vertices': args.vertices,
                'edge_length': args.edge_length,
                'smooth_iterations': args.smooth,
                'rosy': args.rosy,
                'posy': args.posy,
                'deterministic': args.deterministic,
                'dominant': args.dominant,
                'intrinsic': not args.no_intrinsic,
                'quiet': args.quiet,
                'timeout': args.timeout
            }
        
        results = batch_remesh(
            input_files,
            output_dir,
            method=args.method,
            suffix=args.suffix,
            **kwargs
        )
        
        # Return non-zero if any failed
        return 0 if all(results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
