"""Java manifest parser tests — pom.xml + Gradle."""

from __future__ import annotations

from pathlib import Path

from connectors.github.src.stacks.java.parsers import parse_gradle, parse_pom


# ---------------------------------------------------------------------------
# pom.xml
# ---------------------------------------------------------------------------

POM_NS = """\
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>0.1.0</version>
  <dependencies>
    <dependency>
      <groupId>dev.langchain4j</groupId>
      <artifactId>langchain4j-anthropic</artifactId>
      <version>0.35.0</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
      <version>3.3.4</version>
    </dependency>
  </dependencies>
</project>
"""

POM_NO_NS = """\
<project>
  <dependencies>
    <dependency>
      <groupId>org.springframework.ai</groupId>
      <artifactId>spring-ai-openai-spring-boot-starter</artifactId>
      <version>1.0.0-M3</version>
    </dependency>
  </dependencies>
</project>
"""


class TestParsePom:
    def test_extracts_namespaced_pom(self, tmp_path: Path) -> None:
        path = tmp_path / "pom.xml"
        path.write_text(POM_NS)
        deps = parse_pom(path)
        names = {d["name"] for d in deps}
        assert "langchain4j-anthropic" in names
        assert "spring-boot-starter-web" in names

    def test_records_groupid_and_version(self, tmp_path: Path) -> None:
        path = tmp_path / "pom.xml"
        path.write_text(POM_NS)
        deps = {d["name"]: d for d in parse_pom(path)}
        assert deps["langchain4j-anthropic"]["group"] == "dev.langchain4j"
        assert deps["langchain4j-anthropic"]["version"] == "0.35.0"

    def test_handles_pom_without_namespace(self, tmp_path: Path) -> None:
        path = tmp_path / "pom.xml"
        path.write_text(POM_NO_NS)
        deps = parse_pom(path)
        names = {d["name"] for d in deps}
        assert "spring-ai-openai-spring-boot-starter" in names

    def test_unparsable_pom_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "pom.xml"
        path.write_text("<not really xml")
        assert parse_pom(path) == []


# ---------------------------------------------------------------------------
# build.gradle / .kts
# ---------------------------------------------------------------------------

GRADLE_GROOVY = """\
dependencies {
    implementation 'dev.langchain4j:langchain4j-anthropic:0.35.0'
    implementation "org.springframework.boot:spring-boot-starter-web:3.3.4"
    api 'com.example:utils'
    testImplementation 'org.junit.jupiter:junit-jupiter:5.10.0'
}
"""

GRADLE_KTS = """\
dependencies {
    implementation("dev.langchain4j:langchain4j-open-ai:0.35.0")
    implementation("org.springframework.ai:spring-ai-bedrock-ai-spring-boot-starter:1.0.0-M3")
    runtimeOnly("software.amazon.awssdk:bedrockruntime:2.28.0")
}
"""


class TestParseGradle:
    def test_groovy_implementation_strings(self, tmp_path: Path) -> None:
        path = tmp_path / "build.gradle"
        path.write_text(GRADLE_GROOVY)
        deps = {d["name"]: d for d in parse_gradle(path)}
        assert "langchain4j-anthropic" in deps
        assert deps["langchain4j-anthropic"]["group"] == "dev.langchain4j"
        assert deps["langchain4j-anthropic"]["version"] == "0.35.0"

    def test_groovy_handles_missing_version(self, tmp_path: Path) -> None:
        path = tmp_path / "build.gradle"
        path.write_text(GRADLE_GROOVY)
        deps = {d["name"]: d for d in parse_gradle(path)}
        assert deps["utils"]["version"] == ""

    def test_kts_implementation_calls(self, tmp_path: Path) -> None:
        path = tmp_path / "build.gradle.kts"
        path.write_text(GRADLE_KTS)
        deps = {d["name"]: d for d in parse_gradle(path)}
        assert "langchain4j-open-ai" in deps
        assert "spring-ai-bedrock-ai-spring-boot-starter" in deps
        assert "bedrockruntime" in deps

    def test_dedups_by_group_and_artifact(self, tmp_path: Path) -> None:
        path = tmp_path / "build.gradle"
        path.write_text(
            GRADLE_GROOVY + "\nimplementation 'dev.langchain4j:langchain4j-anthropic:0.35.0'\n"
        )
        deps = parse_gradle(path)
        names = [d["name"] for d in deps]
        assert names.count("langchain4j-anthropic") == 1
