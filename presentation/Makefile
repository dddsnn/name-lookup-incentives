PRIMARIES:=slides.pdf
BUILDDIR:=.build
LATEX=lualatex --interaction=nonstopmode --shell-escape %O %S
LATEXMK=latexmk -pdf -pdflatex="$(LATEX)" -use-make -M -MP

.PHONY:all
all:$(PRIMARIES)

$(PRIMARIES):%.pdf: $(BUILDDIR)/%.pdf
	cp '$<' .

$(BUILDDIR)/%.pdf: %.tex
	@mkdir -p $(@D)
	$(LATEXMK) -MF $@.d --outdir=$(BUILDDIR) $<

.PHONY:clean
clean:
	rm -r $(BUILDDIR) $(PRIMARIES)

include $(wildcard $(BUILDDIR)/*.d)
