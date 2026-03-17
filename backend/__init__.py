"""Meridian backend package.

This file makes the repository-root ``backend`` directory an explicit Python
package so imports such as ``backend.api.routes`` resolve consistently in local
development, pytest, and GitHub Actions.
"""
