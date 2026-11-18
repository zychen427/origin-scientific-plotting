from .app import mcp

from .tools import labtalk  # noqa: F401
from .tools import worksheet  # noqa: F401
from .tools import graph  # noqa: F401
from .tools import style  # noqa: F401
from .tools import fitting  # noqa: F401
from .tools import project  # noqa: F401
from .tools import matrix  # noqa: F401
from .tools import analysis  # noqa: F401
from .tools import precise_excel  # noqa: F401
from .tools import batch_workflows  # noqa: F401
from .tools import research_workflows  # noqa: F401
from .tools import spectrum_workflows  # noqa: F401
from .tools import resumable  # noqa: F401
from .tools import workflow_templates  # noqa: F401

from .skills import register_skills

register_skills(mcp)

if __name__ == "__main__":
    mcp.run(transport="stdio")
