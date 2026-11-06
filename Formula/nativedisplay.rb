class Nativedisplay < Formula
  desc "Native display resizing and desktop reduction for remote devices"
  homepage "https://github.com/hailports/Native"
  license "MIT"
  head "https://github.com/hailports/Native.git", branch: "main"
  depends_on "python@3.12"
  depends_on "displayplacer"

  def install
    python = Formula["python@3.12"].opt_bin/"python3.12"
    system python, "-m", "pip", "install", *std_pip_args, "."
  end

  test do
    assert_match "native", shell_output("#{bin}/native --help")
  end
end
