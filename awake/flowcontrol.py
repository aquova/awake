# This file is part of Awake - GB decompiler.
# Copyright (C) 2012  Wojciech Marczenko (devdri) <wojtek.marczenko@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from . import instruction
from . import operand
from . import context
from . import regutil
from . import depend
from . import placeholders
from . import address

class Label(instruction.BaseOp):
    def __init__(self, addr):
        super(Label, self).__init__('label', [operand.AddressConstant(addr)])
        self.addr = address.fromVirtual(0)
        self.gotos = set()
        self.breaks = set()
        self.continues = set()
        self.needed = regutil.ALL_REGS - set(['FZ', 'FC', 'FN', 'FH'])
        self.depset = depend.unknown()

    def addGoto(self, x):
        self.gotos.add(x)

    def addBreak(self, x):
        self.breaks.add(x)

    def addContinue(self, x):
        self.continues.add(x)

    def optimizedWithContext(self, ctx):
        if self.gotos or self.breaks or self.continues:
            for w in self.depset.writes:
                ctx.setValueComplex(w)
        return self

    def setContextWrites(self, writes):
        self.depset.writes = writes

    def getDependencies(self, needed):
        return needed

    def getDependencySet(self):
        return depend.DependencySet()

    def optimizeDependencies(self, needed):
        if self.gotos or self.breaks or self.continues:
            self.needed = set(needed)
            self.depset.reads = needed
            return self
        else:
            return None

    def signature(self):
        ins = regutil.joinRegisters(self.needed - set(['mem']))
        return ' @ ' + ', '.join(sorted(str(x) for x in ins if not isinstance(x, address.Address)))

    def render(self, renderer, indent=0, labels=None):
        if not self.gotos:
            return

        if not renderer.emptyLine:
            renderer.newline()
        renderer.addLegacy('<a name="{0}">label_{1}</a>: {2}'.format(self.addr, self.addr, self.signature()))

class FlowTerminator(instruction.BaseOp):
    def __init__(self, name, target=None):
        if target:
            operands = [operand.LabelAddress(target)]
        else:
            operands = []
        super(FlowTerminator, self).__init__(name, operands)
        self.target = target

    def hasContinue(self):
        return False

    def optimizeDependencies(self, needed):
        return self

class Goto(FlowTerminator):
    def __init__(self, label):
        super(Goto, self).__init__("goto", label.addr)
        self.target_label = label
        label.addGoto(self)

    def getDependencies(self, needed):
        return self.target_label.needed

    def getDependencySet(self):
        return depend.DependencySet(self.target_label.depset.reads, set())

    def signature(self):
        ins = regutil.joinRegisters(self.target_label.needed - set(['mem']))
        return ' @ ' + ', '.join(sorted(str(x) for x in ins if not isinstance(x, address.Address)))

class Break(FlowTerminator):
    def __init__(self, label):
        super(Break, self).__init__("break")
        self.target_label = label
        label.addBreak(self)

    def getDependencies(self, needed):
        return self.target_label.needed

    def getDependencySet(self):
        return depend.DependencySet(self.target_label.depset.reads, set())

    def signature(self):
        ins = regutil.joinRegisters(self.target_label.needed - set(['mem']))
        return ' @ ' + ', '.join(sorted(str(x) for x in ins if not isinstance(x, address.Address)))

class Continue(FlowTerminator):
    def __init__(self, label):
        super(Continue, self).__init__("continue")
        self.target_label = label
        label.addContinue(self)

    def getDependencies(self, needed):
        return self.target_label.needed

    def getDependencySet(self):
        #return self.target_label.depset
        #TODO: XXX: return depend.DependencySet(self.target_label.depset.reads, regutil.ALL_REGS)
        return depend.DependencySet(self.target_label.depset.reads, set())

    def signature(self):
        ins = regutil.joinRegisters(self.target_label.needed - set(['mem']))
        return ' @ ' + ', '.join(sorted(str(x) for x in ins if not isinstance(x, address.Address)))

class Return(FlowTerminator):
    def __init__(self):
        super(Return, self).__init__("return")

    def getDependencySet(self):
        return depend.DependencySet()

    def getDependencies(self, needed):
        return needed

class Block(instruction.Instruction):
    def __init__(self, contents):
        self.contents = []
        for x in contents:
            self.contents += x.splitToSimple()
        #self.contents = contents

    def __bool__(self):
        return bool(self.contents)
        
    def __nonzero__(self):
        return bool(self.contents)

    """Heuristic code complexity inside block"""
    def complexity(self):
        out = 0
        for x in self.contents:
            if hasattr(x, 'complexity'):
                out += x.complexity()
            out += 1
        return out

    def hasContinue(self):
        if not self.contents:
            return True
        return self.contents[-1].hasContinue()

    def render(self, renderer, indent=0):
        for el in self.contents:
            el.render(renderer, indent)

    def __str__(self):
        return 'block'+str(len(self.contents))+':'+str(bool(self))+'(' + ','.join(sorted(str(el) for el in self.contents)) + ')'

    def optimizedWithContext(self, context):
        contents = []
        for instr in self.contents:
            instr = instr.optimizedWithContext(context)
            contents.append(instr)
        return Block(contents)

    def getDependencies(self, needed):
        for instr in reversed(self.contents):
            needed = instr.getDependencies(needed)
        return needed

    def getDependencySet(self):
        cur = depend.DependencySet()
        for instr in reversed(self.contents):
            cur = depend.joinDependencies(instr.getDependencySet(), cur)
        return cur

    def optimizeDependencies(self, needed):
        contents = []
        for instr in reversed(self.contents):
            instr = instr.optimizeDependencies(needed)
            if instr:
                needed = instr.getDependencies(needed)
                contents.append(instr)
        contents.reverse()
        return Block(contents)

    def getInstructions(self, out):
        for x in self.contents:
            if hasattr(x, 'getInstructions'):
                x.getInstructions(out)
            else:
                out.add(x)

class Switch(instruction.Instruction):
    def __init__(self, addr, branches, arg=None, base_value=0):
        self.name = 'switch-highlevel'
        if not arg:
            self.arg = placeholders.A
        else:
            self.arg = arg
        self.addr = addr
        self.branches = branches
        self.jtAddr = operand.JumpTableAddress(addr.offset(1))
        self.base_value = base_value

    def valueForBranch(self, i):
        return operand.Constant(self.base_value + i)

    def render(self, renderer, indent):
        renderer.newInstruction(self.addr, indent)
        renderer.instructionName('switch')
        renderer.add(' (')
        self.arg.render(renderer)
        renderer.add(', ')
        self.jtAddr.render(renderer)
        renderer.add(') {')

        for (i, b) in enumerate(self.branches):
            renderer.newInstruction(self.addr, indent)
            renderer.instructionName('case')
            renderer.add(' ')
            self.valueForBranch(i).render(renderer)
            renderer.add(':')
            b.render(renderer, indent+1)

        renderer.newInstruction(self.addr, indent)
        renderer.add('}')

    def getInstructions(self, out):
        for b in self.branches:
            b.getInstructions(out)
        out.add(self)

    def optimizedWithContext(self, ctx):
        arg = self.arg.optimizedWithContext(ctx)

        base_value = self.base_value

        from . import operator
        if isinstance(arg, operator.Sub) and arg.right.value is not None:
            base_value += arg.right.value
            arg = arg.left

        branches = [b.optimizedWithContext(ctx.clone()) for b in self.branches]
        for b in self.branches:
            for w in b.getDependencySet().writes:
                ctx.setValueComplex(w)
        return Switch(self.addr, branches, arg, base_value)

    def getDependencies(self, needed):
        deps = self.arg.getDependencies()
        for b in self.branches:
            deps |= b.getDependencies(needed)
        return deps

    def getDependencySet(self):
        deps = depend.DependencySet()
        for b in self.branches:
            deps = depend.parallel(b.getDependencySet(), deps)
        return depend.DependencySet(deps.reads | self.arg.getDependencies(), deps.writes)

    def optimizeDependencies(self, needed):
        branches = [b.optimizeDependencies(needed) for b in self.branches]
        return Switch(self.addr, branches, self.arg, self.base_value)


class If(instruction.Instruction):
    def __init__(self, split, cond, option_a, option_b):
        self.name = 'if'
        self.split = split
        self.addr = split
        self.cond = cond
        self.option_a = option_a
        self.option_b = option_b

    def is_break_condition(self):  # TODO: XXX: not nice...
        if self.option_b or not self.option_a:
            return False
        if len(self.option_a.contents) != 1:
            return False
        instr = self.option_a.contents[0]
        return instr.name == 'break'

    def hasContinue(self):
        if not self.option_a or not self.option_b:
            return True
        return self.option_a.hasContinue() or self.option_b.hasContinue()

    def render(self, renderer, indent):
        addr = self.addr
        renderer.newInstruction(addr, indent)
        renderer.instructionName('if')
        renderer.add(' (')
        self.cond.render(renderer)
        renderer.add(') {')

        if not self.option_a and not self.option_b:
            renderer.newInstruction(addr, indent)
            renderer.instructionName('WARN: empty if')

        elif not self.option_a:
            self.option_b.render(renderer, indent+1)
        else:
            self.option_a.render(renderer, indent+1)

        if self.option_b and self.option_a:
            renderer.newInstruction(addr, indent)
            renderer.instructionName('} else {')
            self.option_b.render(renderer, indent+1)

        renderer.newInstruction(addr, indent)
        renderer.add('}')

    def optimizedWithContext(self, ctx):

        cond = self.cond.optimizedWithContext(ctx)

        #ctx.invalidateComplex()  # TODO: XXX

        option_a = None
        if self.option_a:
            option_a = self.option_a.optimizedWithContext(ctx.clone())
        option_b = None
        if self.option_b:
            option_b = self.option_b.optimizedWithContext(ctx.clone())

        if self.option_a:
            for w in self.option_a.getDependencySet().writes:
                ctx.setValueComplex(w)
        if self.option_b:
            for w in self.option_b.getDependencySet().writes:
                ctx.setValueComplex(w)

        return If(self.split, cond, option_a, option_b)

    def getDependencies(self, needed):
        deps = set()
        if self.option_a:
            deps |= self.option_a.getDependencies(needed)
        else:
            deps |= needed
        if self.option_b:
            deps |= self.option_b.getDependencies(needed)
        else:
            deps |= needed
        deps |= self.cond.getDependencies()
        return deps

    def getDependencySet(self):
        deps = depend.DependencySet()
        if self.option_a:
            deps = depend.parallel(self.option_a.getDependencySet(), deps)
        if self.option_b:
            deps = depend.parallel(self.option_b.getDependencySet(), deps)
        cond_deps = depend.DependencySet(self.cond.getDependencies())
        return depend.joinDependencies(cond_deps, deps)

    def optimizeDependencies(self, needed):
        option_a = None
        if self.option_a:
            option_a = self.option_a.optimizeDependencies(needed)
        option_b = None
        if self.option_b:
            option_b = self.option_b.optimizeDependencies(needed)
        return If(self.split, self.cond, option_a, option_b)

    def getInstructions(self, out):
        if self.option_a:
            self.option_a.getInstructions(out)
        if self.option_b:
            self.option_b.getInstructions(out)
        out.add(self)

    def getMemreads(self):
        return self.cond.getMemreads()

class LoopWhile(instruction.Instruction):

    def complexity(self):
        return 4 + self.inner.complexity()

    def getInstructions(self, out):
        self.inner.getInstructions(out)
        out.add(self)

class DoWhile(LoopWhile):
    def __init__(self, inner, postcond, continue_label):
        self.name = 'do-while'
        self.addr = address.fromVirtual(0)
        self.inner = inner
        self.postcond = postcond
        self.continue_label = continue_label
        continue_label.addContinue(self)

    def render(self, renderer, indent):
        addr = "0000:0000"  # TODO: inner first addr

        renderer.newInstruction(addr, indent)
        renderer.instructionName('do {')
        renderer.instructionSignature(self.signature())

        self.inner.render(renderer, indent+1)

        renderer.newInstruction(addr, indent)
        renderer.instructionName('} while (')
        self.postcond.render(renderer)
        renderer.add(')')

    def optimizedWithContext(self, ctx):

        self.continue_label.setContextWrites(self.getDependencySet().writes)

        #ctx.invalidateAll()
        #ctx2 = context.Context()
        ctx2 = ctx

        inner = self.inner.optimizedWithContext(ctx2)
        postcond = self.postcond.optimizedWithContext(ctx2)
        return DoWhile(inner, postcond, self.continue_label)

    def getDependencies(self, needed):
        pass1 = self.inner.getDependencies(needed | self.postcond.getDependencies())
        pass2 = self.inner.getDependencies(pass1)

        pass3 = self.inner.getDependencies(pass2)
        assert pass2 == pass3

        return pass2

    def getDependencySet(self):
        x = self.inner.getDependencySet()
        postcond_deps = depend.DependencySet(self.postcond.getDependencies())
        return depend.joinDependencies(x, postcond_deps)

    def optimizeDependencies(self, needed):
        if self.continue_label:
            self.continue_label.optimizeDependencies(self.getDependencies(needed))
        inner = self.inner.optimizeDependencies(needed | self.postcond.getDependencies() | self.getDependencies(needed))
        return DoWhile(inner, self.postcond, self.continue_label)

    def signature(self):
        deps = self.inner.getDependencySet()
        loopvars = deps.writes & (deps.reads | self.postcond.getDependencies())
        loopvars -= set(['mem'])
        loopvars = regutil.joinRegisters(loopvars)
        return " @ loopvars: " + ", ".join(sorted(str(x) for x in loopvars if not isinstance(x, address.Address)))

    def getMemreads(self):
        return self.postcond.getMemreads()

class While(LoopWhile):
    def __init__(self, inner, continue_label):
        self.name = 'while'
        self.inner = inner
        self.addr = address.fromVirtual(0)
        self.continue_label = continue_label
        continue_label.addContinue(self)

    def render(self, renderer, indent):
        addr = "0000:0000"  # TODO: inner first addr

        renderer.newInstruction(addr, indent)
        renderer.instructionName('while (1) {')
        renderer.instructionSignature(self.signature())

        self.inner.render(renderer, indent+1)

        renderer.newInstruction(addr, indent)
        renderer.instructionName('}')

    def hasContinue(self):
        return False

    def optimizedWithContext(self, ctx):
        ctx.invalidateAll()
        inner = self.inner.optimizedWithContext(context.Context())
        return While(inner, self.continue_label)

    def getDependencies(self, needed):
        pass1 = self.inner.getDependencies(needed)
        pass2 = self.inner.getDependencies(pass1)

        pass3 = self.inner.getDependencies(pass2)
        assert pass2 == pass3

        return pass2

    def getDependencySet(self):
        return self.inner.getDependencySet()

    def optimizeDependencies(self, needed):
        if self.continue_label:
            self.continue_label.optimizeDependencies(self.getDependencies(needed))
        inner = self.inner.optimizeDependencies(needed | self.getDependencies(needed))
        return While(inner, self.continue_label)

    def signature(self):
        deps = self.inner.getDependencySet()
        loopvars = deps.writes & deps.reads
        loopvars -= set(['mem'])
        loopvars = regutil.joinRegisters(loopvars)
        return " @ loopvars: " + ", ".join(sorted(str(x) for x in loopvars if not isinstance(x, address.Address)))

