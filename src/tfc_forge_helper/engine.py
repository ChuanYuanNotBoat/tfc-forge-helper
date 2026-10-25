import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .assets import AssetError, ResolvedAtlas, find_tfc_jar, resolve_atlas
from .discovery import discover, resource_signature
from .profile import Profile
from .solver import Solution, solve
from .vision import Detector, Observation


@dataclass(frozen=True)
class Config:
    instance: str = ""
    jar: str = ""
    packs: tuple[str, ...] = ()
    profile: str = ""
    auto_instance: bool = True


@dataclass(frozen=True)
class Analysis:
    observation: Observation
    solution: Solution
    assets: ResolvedAtlas
    instance: str


class Engine:
    def __init__(self):
        self._detector = None
        self._atlas = None
        self._key = None
        self._last_discovery = -100.0
        self._candidates = []
        self._discovery_notices = []
        self.instance = ""
        self.revision = 0
        self.pid = None
        self._solution_key = None
        self._solution = None

    @property
    def candidates(self):
        return self._candidates

    def refresh(self, config: Config, force: bool = False, *,
                discover_process: bool = True) -> tuple[ResolvedAtlas, Profile]:
        instance = Path(config.instance) if config.instance else None
        if config.auto_instance:
            if discover_process and (force or time.monotonic() - self._last_discovery >= 5):
                candidates, self._discovery_notices = discover()
                self._candidates = []
                for candidate in candidates:
                    try:
                        find_tfc_jar(candidate.path)
                        self._candidates.append(candidate)
                    except (AssetError, OSError):
                        continue
                self._last_discovery = time.monotonic()
            active = [c for c in self._candidates if c.pid is not None]
            eligible = active or self._candidates
            if len(eligible) > 1:
                raise AssetError("发现多个 TFC 实例，请在资源设置中选择一个并关闭自动选择")
            instance = eligible[0].path if eligible else None
        elif discover_process and instance is not None and (force or time.monotonic() - self._last_discovery >= 5):
            # An explicitly selected instance still needs its actual game PID
            # for window-following screenshots and opt-in automatic input.
            self._candidates, self._discovery_notices = discover()
            self._last_discovery = time.monotonic()
        self.instance = str(instance or "")
        self.pid = next((c.pid for c in self._candidates if c.path == instance and c.pid is not None), None)
        jar = Path(config.jar) if config.jar else None
        packs = tuple(Path(x) for x in config.packs)
        profile_path = Path(config.profile) if config.profile else None
        profile_key = None
        if profile_path:
            st = profile_path.stat()
            profile_key = (st.st_mtime_ns, st.st_size)
        key = (config, self.instance, resource_signature(instance, jar, packs), profile_key)
        if force or key != self._key:
            # Only publish the new cache after every stage has succeeded.
            profile = Profile.load(profile_path)
            atlas = resolve_atlas(instance, jar, packs, profile.resource)
            unknown = [w for w in atlas.warnings if w.startswith("内置资源包")]
            if unknown:
                raise AssetError("；".join(unknown) + "。请补充资源，避免使用错误模板")
            detector = Detector(atlas, profile)
            self._atlas, self._detector, self._key = atlas, detector, key
            self.revision += 1
        return self._atlas, self._detector.profile

    def refresh_automation(self, config: Config) -> tuple[ResolvedAtlas, Profile]:
        # A running sequence stays attached to its initial process. Native input
        # validates that PID/window on every click; resource signatures are still
        # checked here. Expensive launcher/process discovery resumes after the run.
        discover_process = self._key is None or config != self._key[0]
        return self.refresh(config, discover_process=discover_process)

    def analyze(self, image: Image.Image, config: Config, tolerance: int = 0) -> Analysis:
        atlas, _ = self.refresh(config)
        observation = self._detector.detect(image)
        solution_key = (observation.current, observation.target, observation.rules, observation.history, tolerance)
        if solution_key != self._solution_key:
            solution = solve(observation.current, observation.target, observation.rules,
                             observation.history, tolerance=tolerance)
            self._solution, self._solution_key = solution, solution_key
        solution = self._solution
        return Analysis(observation, solution, atlas, self.instance)
